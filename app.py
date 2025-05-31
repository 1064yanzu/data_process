from flask import Flask, render_template, request, jsonify, send_file, session
import pandas as pd
import numpy as np
from snownlp import SnowNLP
import json
import os
import pickle
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.graph_objs as go
import plotly.utils
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.svm import SVC
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
import jieba
import openai
from dotenv import load_dotenv
import io
import base64
import csv
import concurrent.futures
import time
import uuid
import threading
from werkzeug.utils import secure_filename
import requests
import logging
import shutil
import sqlite3
from collections import defaultdict
import hashlib

# 加载环境变量
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
# app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 移除16MB限制
app.config['UPLOAD_FOLDER'] = 'uploads'

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('data', exist_ok=True)
os.makedirs('data/backups', exist_ok=True)
os.makedirs('data/versions', exist_ok=True)
os.makedirs('models', exist_ok=True)
os.makedirs('exports', exist_ok=True)

# 全局变量
DATA_FILE = 'data/sentiment_data.json'
CONFIG_FILE = 'data/llm_config.json'
TASKS_FILE = 'data/processing_tasks.json'
DATABASE_FILE = 'data/sentiment_db.sqlite'

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 任务状态管理
processing_tasks = {}
task_lock = threading.Lock()

# 数据缓存
data_cache = {
    'data': None,
    'last_modified': None,
    'version': None
}
cache_lock = threading.Lock()

class DataManager:
    """数据管理器 - 处理版本控制、备份、回滚等"""
    
    def __init__(self):
        self.init_database()
        self.current_version = self.get_latest_version()
        
    def init_database(self):
        """初始化SQLite数据库"""
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        # 创建数据表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS data_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT UNIQUE,
                timestamp TEXT,
                operation TEXT,
                description TEXT,
                data_hash TEXT,
                file_path TEXT,
                created_by TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS operation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                operation_type TEXT,
                operation_data TEXT,
                affected_count INTEGER,
                user_id TEXT,
                version_before TEXT,
                version_after TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def generate_version_id(self):
        """生成版本ID"""
        return f"v_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    
    def calculate_data_hash(self, data):
        """计算数据哈希值"""
        data_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(data_str.encode('utf-8')).hexdigest()
    
    def save_version(self, data, operation="manual_save", description="手动保存", user_id="system"):
        """保存数据版本"""
        try:
            version_id = self.generate_version_id()
            timestamp = datetime.now().isoformat()
            data_hash = self.calculate_data_hash(data)
            
            # 检查是否需要保存（数据是否有变化）
            if self.current_version:
                last_hash = self.get_version_hash(self.current_version)
                if last_hash == data_hash:
                    logger.info("数据无变化，跳过版本保存")
                    return self.current_version
            
            # 保存数据文件
            version_file = f"data/versions/{version_id}.json"
            with open(version_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 创建备份
            backup_file = f"data/backups/backup_{version_id}.json"
            shutil.copy2(version_file, backup_file)
            
            # 保存版本信息到数据库
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO data_versions 
                (version_id, timestamp, operation, description, data_hash, file_path, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (version_id, timestamp, operation, description, data_hash, version_file, user_id))
            
            conn.commit()
            conn.close()
            
            # 更新当前版本
            self.current_version = version_id
            
            # 清理旧版本（保留最近20个版本）
            self.cleanup_old_versions()
            
            logger.info(f"数据版本已保存: {version_id}")
            return version_id
            
        except Exception as e:
            logger.error(f"保存数据版本失败: {e}")
            return None
    
    def load_version(self, version_id):
        """加载指定版本的数据"""
        try:
            version_file = f"data/versions/{version_id}.json"
            if not os.path.exists(version_file):
                raise FileNotFoundError(f"版本文件不存在: {version_id}")
            
            with open(version_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return data
            
        except Exception as e:
            logger.error(f"加载数据版本失败: {e}")
            return None
    
    def rollback_to_version(self, version_id, user_id="system"):
        """回滚到指定版本"""
        try:
            # 加载目标版本数据
            data = self.load_version(version_id)
            if data is None:
                return False
            
            # 保存当前数据作为回滚前的版本
            current_data = self.load_current_data()
            if current_data:
                self.save_version(
                    current_data, 
                    operation="pre_rollback", 
                    description=f"回滚前自动保存 (目标版本: {version_id})",
                    user_id=user_id
                )
            
            # 执行回滚
            rollback_version = self.save_version(
                data,
                operation="rollback",
                description=f"回滚到版本 {version_id}",
                user_id=user_id
            )
            
            # 更新主数据文件
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 清除缓存
            self.clear_cache()
            
            # 记录操作历史
            self.record_operation(
                operation_type="rollback",
                operation_data={"target_version": version_id, "rollback_version": rollback_version},
                affected_count=len(data),
                user_id=user_id,
                version_before=self.current_version,
                version_after=rollback_version
            )
            
            logger.info(f"成功回滚到版本: {version_id}")
            return True
            
        except Exception as e:
            logger.error(f"回滚失败: {e}")
            return False
    
    def get_version_list(self, limit=50):
        """获取版本列表"""
        try:
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT version_id, timestamp, operation, description, created_by
                FROM data_versions
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,))
            
            versions = cursor.fetchall()
            conn.close()
            
            return [
                {
                    'version_id': v[0],
                    'timestamp': v[1],
                    'operation': v[2],
                    'description': v[3],
                    'created_by': v[4]
                }
                for v in versions
            ]
            
        except Exception as e:
            logger.error(f"获取版本列表失败: {e}")
            return []
    
    def get_latest_version(self):
        """获取最新版本ID"""
        versions = self.get_version_list(limit=1)
        return versions[0]['version_id'] if versions else None
    
    def get_version_hash(self, version_id):
        """获取版本哈希值"""
        try:
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            
            cursor.execute('SELECT data_hash FROM data_versions WHERE version_id = ?', (version_id,))
            result = cursor.fetchone()
            conn.close()
            
            return result[0] if result else None
            
        except Exception as e:
            logger.error(f"获取版本哈希值失败: {e}")
            return None
    
    def cleanup_old_versions(self, keep_count=20):
        """清理旧版本文件"""
        try:
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            
            # 获取需要删除的版本
            cursor.execute('''
                SELECT version_id, file_path FROM data_versions
                ORDER BY timestamp DESC
                LIMIT -1 OFFSET ?
            ''', (keep_count,))
            
            old_versions = cursor.fetchall()
            
            for version_id, file_path in old_versions:
                # 删除版本文件
                if os.path.exists(file_path):
                    os.remove(file_path)
                
                # 删除备份文件
                backup_file = f"data/backups/backup_{version_id}.json"
                if os.path.exists(backup_file):
                    os.remove(backup_file)
                
                # 删除数据库记录
                cursor.execute('DELETE FROM data_versions WHERE version_id = ?', (version_id,))
            
            conn.commit()
            conn.close()
            
            if old_versions:
                logger.info(f"已清理 {len(old_versions)} 个旧版本")
                
        except Exception as e:
            logger.error(f"清理旧版本失败: {e}")
    
    def record_operation(self, operation_type, operation_data, affected_count=0, user_id="system", version_before=None, version_after=None):
        """记录操作历史"""
        try:
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO operation_history
                (timestamp, operation_type, operation_data, affected_count, user_id, version_before, version_after)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                operation_type,
                json.dumps(operation_data, ensure_ascii=False),
                affected_count,
                user_id,
                version_before,
                version_after
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"记录操作历史失败: {e}")
    
    def get_operation_history(self, limit=100):
        """获取操作历史"""
        try:
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT timestamp, operation_type, operation_data, affected_count, user_id, version_before, version_after
                FROM operation_history
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,))
            
            history = cursor.fetchall()
            conn.close()
            
            return [
                {
                    'timestamp': h[0],
                    'operation_type': h[1],
                    'operation_data': json.loads(h[2]) if h[2] else {},
                    'affected_count': h[3],
                    'user_id': h[4],
                    'version_before': h[5],
                    'version_after': h[6]
                }
                for h in history
            ]
            
        except Exception as e:
            logger.error(f"获取操作历史失败: {e}")
            return []
    
    def load_current_data(self):
        """加载当前数据"""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return []
        except Exception as e:
            logger.error(f"加载当前数据失败: {e}")
            return []
    
    def clear_cache(self):
        """清除数据缓存"""
        global data_cache
        with cache_lock:
            data_cache['data'] = None
            data_cache['last_modified'] = None
            data_cache['version'] = None

class CachedDataLoader:
    """缓存数据加载器 - 提升性能"""
    
    @staticmethod
    def load_data_with_cache():
        """使用缓存加载数据"""
        global data_cache
        
        try:
            # 检查文件修改时间
            if os.path.exists(DATA_FILE):
                file_mtime = os.path.getmtime(DATA_FILE)
                
                with cache_lock:
                    # 如果缓存有效，直接返回
                    if (data_cache['data'] is not None and 
                        data_cache['last_modified'] == file_mtime):
                        return data_cache['data']
                    
                    # 重新加载数据
                    with open(DATA_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # 更新缓存
                    data_cache['data'] = data
                    data_cache['last_modified'] = file_mtime
                    data_cache['version'] = data_manager.current_version
                    
                    return data
            else:
                return []
                
        except Exception as e:
            logger.error(f"缓存加载数据失败: {e}")
            return []
    
    @staticmethod
    def save_data_with_cache(data, operation="update", description="数据更新", user_id="system"):
        """保存数据并更新缓存"""
        global data_cache
        
        try:
            # 保存到主文件
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 创建版本
            version_id = data_manager.save_version(data, operation, description, user_id)
            
            # 更新缓存
            with cache_lock:
                data_cache['data'] = data
                data_cache['last_modified'] = os.path.getmtime(DATA_FILE)
                data_cache['version'] = version_id
            
            # 记录操作
            data_manager.record_operation(
                operation_type=operation,
                operation_data={"description": description},
                affected_count=len(data),
                user_id=user_id,
                version_after=version_id
            )
            
            return True
            
        except Exception as e:
            logger.error(f"缓存保存数据失败: {e}")
            return False

# 初始化数据管理器
data_manager = DataManager()

def ensure_data_file():
    """确保数据文件存在"""
    if not os.path.exists(DATA_FILE):
        initial_data = []
        CachedDataLoader.save_data_with_cache(
            initial_data, 
            operation="init", 
            description="初始化数据文件"
        )

class LLMClient:
    """统一的LLM客户端，支持多种API"""
    
    def __init__(self, config):
        self.config = config
        self.api_type = config.get('api_type', 'openai')
        self.base_url = config.get('base_url', '')
        self.api_key = config.get('api_key', '')
        self.model_name = config.get('model_name', 'gpt-3.5-turbo')
        self.timeout = config.get('timeout', 30)
        self.batch_size = config.get('batch_size', 5)  # 批量处理大小
        
    def predict_sentiment_batch(self, texts):
        """批量预测文本情感"""
        try:
            if self.api_type == 'openai':
                return self._call_openai_api_batch(texts)
            elif self.api_type == 'custom':
                return self._call_custom_api_batch(texts)
            else:
                raise ValueError(f"不支持的API类型: {self.api_type}")
        except Exception as e:
            logger.error(f"LLM API批量调用失败: {e}")
            # 降级使用SnowNLP
            results = []
            for text in texts:
                s = SnowNLP(text)
                results.append({
                    'sentiment': 1 if s.sentiments > 0.5 else 0,
                    'confidence': float(s.sentiments),
                    'source': 'snownlp_fallback'
                })
            return results
    
    def _call_openai_api_batch(self, texts):
        """批量调用OpenAI API"""
        openai.api_key = self.api_key
        if self.base_url:
            openai.api_base = self.base_url
        
        # 构建批量分析的prompt
        batch_prompt = """请分析以下中文文本的情感倾向，对每条文本只回答"正面"或"负面"，按顺序返回结果，用换行符分隔：

"""
        for i, text in enumerate(texts, 1):
            batch_prompt += f"{i}. {text}\n"
        
        batch_prompt += "\n请按顺序返回每条文本的情感分析结果："
            
        response = openai.ChatCompletion.create(
            model=self.model_name,
            messages=[{"role": "user", "content": batch_prompt}],
            max_tokens=len(texts) * 10,
            temperature=0.1,
            timeout=self.timeout
        )
        
        result_text = response.choices[0].message.content.strip()
        result_lines = [line.strip() for line in result_text.split('\n') if line.strip()]
        
        results = []
        for i, text in enumerate(texts):
            if i < len(result_lines):
                sentiment = 1 if "正面" in result_lines[i] else 0
            else:
                sentiment = 0  # 默认值
            
            results.append({
                'sentiment': sentiment,
                'confidence': 0.85,
                'source': 'openai_batch'
            })
        
        return results
    
    def _call_custom_api_batch(self, texts):
        """批量调用自定义API"""
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        # 构建批量分析的prompt
        batch_content = "分析以下文本的情感，对每条只回答'正面'或'负面'：\n"
        for i, text in enumerate(texts, 1):
            batch_content += f"{i}. {text}\n"
        
        payload = {
            'model': self.model_name,
            'messages': [
                {
                    'role': 'user', 
                    'content': batch_content
                }
            ],
            'max_tokens': len(texts) * 10,
            'temperature': 0.1
        }
        
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content'].strip()
            result_lines = [line.strip() for line in content.split('\n') if line.strip()]
            
            results = []
            for i, text in enumerate(texts):
                if i < len(result_lines):
                    sentiment = 1 if "正面" in result_lines[i] else 0
                else:
                    sentiment = 0
                
                results.append({
                    'sentiment': sentiment,
                    'confidence': 0.80,
                    'source': 'custom_api_batch'
                })
            
            return results
        else:
            raise Exception(f"API调用失败: {response.status_code}")

class SentimentAnalyzer:
    """情感分析器"""
    
    def __init__(self):
        self.models = {}
        self.load_models()
    
    def load_models(self):
        """加载所有训练好的模型"""
        model_dir = 'models'
        if os.path.exists(model_dir):
            for file in os.listdir(model_dir):
                if file.endswith('.pkl'):
                    model_name = file[:-4]
                    try:
                        with open(os.path.join(model_dir, file), 'rb') as f:
                            self.models[model_name] = pickle.load(f)
                        logger.info(f"加载模型: {model_name}")
                    except Exception as e:
                        logger.error(f"加载模型失败 {model_name}: {e}")
    
    def predict(self, text, model_name='default'):
        """预测情感"""
        if model_name in self.models:
            try:
                return self.models[model_name].predict([text])[0]
            except Exception as e:
                logger.error(f"模型预测失败: {e}")
        
        # 使用SnowNLP作为默认预测
        s = SnowNLP(text)
        return 1 if s.sentiments > 0.5 else 0
    
    def predict_proba(self, text, model_name='default'):
        """预测概率"""
        if model_name in self.models:
            try:
                proba = self.models[model_name].predict_proba([text])[0]
                return float(proba[1])  # 正面情感概率
            except Exception as e:
                logger.error(f"模型预测概率失败: {e}")
        
        # 使用SnowNLP
        s = SnowNLP(text)
        return float(s.sentiments)
    
    def train_model(self, texts, labels, model_config):
        """训练新模型"""
        algorithm = model_config.get('algorithm', 'naive_bayes')
        max_features = model_config.get('max_features', 5000)
        ngram_range = tuple(model_config.get('ngram_range', [1, 2]))
        
        # 创建模型
        if algorithm == 'naive_bayes':
            classifier = MultinomialNB()
        elif algorithm == 'svm':
            classifier = SVC(probability=True)
        elif algorithm == 'logistic':
            classifier = LogisticRegression()
        elif algorithm == 'random_forest':
            classifier = RandomForestClassifier()
        else:
            classifier = MultinomialNB()
        
        # 创建管道
        pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(
                max_features=max_features,
                ngram_range=ngram_range,
                stop_words=None
            )),
            ('classifier', classifier)
        ])
        
        # 训练模型
        pipeline.fit(texts, labels)
        
        # 保存模型
        model_name = f"{algorithm}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        model_path = f"models/{model_name}.pkl"
        
        with open(model_path, 'wb') as f:
            pickle.dump(pipeline, f)
        
        self.models[model_name] = pipeline
        
        return model_name

# 初始化分析器
analyzer = SentimentAnalyzer()

def load_llm_config():
    """加载LLM配置，优先使用环境变量"""
    # 默认配置
    config = {
        'api_type': 'openai',
        'base_url': os.getenv('OPENAI_BASE_URL', ''),
        'api_key': os.getenv('OPENAI_API_KEY', ''),
        'model_name': os.getenv('OPENAI_MODEL', 'gpt-3.5-turbo'),
        'timeout': int(os.getenv('API_TIMEOUT', '30')),
        'max_concurrent': int(os.getenv('MAX_CONCURRENT', '5'))
    }
    
    # 如果存在配置文件，合并配置（环境变量优先）
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
                # 只有当环境变量为空时才使用文件配置
                for key, value in file_config.items():
                    if key in config and not config[key]:
                        config[key] = value
        except Exception as e:
            logger.warning(f"读取配置文件失败: {e}")
    
    # 记录API密钥状态（不记录具体值）
    if config['api_key']:
        logger.info(f"API密钥已配置 (长度: {len(config['api_key'])})")
    else:
        logger.warning("未配置API密钥，将使用SnowNLP作为后备")
    
    return config

def save_llm_config(config):
    """保存LLM配置"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def process_batch_texts(texts, task_id, llm_config, review_ratio=0.1):
    """批量处理文本"""
    try:
        with task_lock:
            processing_tasks[task_id] = {
                'status': 'processing',
                'progress': 0,
                'total': len(texts),
                'completed': 0,
                'results': [],
                'errors': []
            }
        
        llm_client = LLMClient(llm_config)
        batch_size = llm_config.get('batch_size', 5)  # 每次处理5条文本
        max_workers = min(llm_config.get('max_concurrent', 3), 10)  # 减少并发数
        
        results = []
        
        def process_text_batch(text_batch):
            try:
                # 处理不同的数据格式
                batch_texts = []
                for item in text_batch:
                    if isinstance(item, str):
                        # 如果是字符串，直接使用
                        text = item.strip()
                    else:
                        # 如果是对象，提取text字段
                        text = item.get('text', '').strip()
                    
                    if text:
                        batch_texts.append(text)
                
                if not batch_texts:
                    return []
                
                # 批量调用LLM
                llm_results = llm_client.predict_sentiment_batch(batch_texts)
                
                batch_results = []
                for i, item in enumerate(text_batch):
                    # 统一处理文本获取
                    if isinstance(item, str):
                        text = item.strip()
                        original_data = {'text': text}
                    else:
                        text = item.get('text', '').strip()
                        original_data = item
                    
                    if not text:
                        continue
                    
                    llm_result = llm_results[i] if i < len(llm_results) else {
                        'sentiment': 0, 'confidence': 0.5, 'source': 'error'
                    }
                    
                    # SnowNLP对比
                    s = SnowNLP(text)
                    snownlp_score = float(s.sentiments)
                    snownlp_pred = 1 if snownlp_score > 0.5 else 0
                    
                    batch_results.append({
                        'text': text,
                        'llm_prediction': llm_result['sentiment'],
                        'llm_confidence': llm_result['confidence'],
                        'llm_source': llm_result['source'],
                        'snownlp_prediction': snownlp_pred,
                        'snownlp_confidence': snownlp_score,
                        'needs_review': False,
                        'timestamp': datetime.now().isoformat(),
                        'original_data': original_data
                    })
                
                return batch_results
                
            except Exception as e:
                logger.error(f"处理文本批次失败: {e}")
                return []
        
        # 分批处理
        text_batches = [texts[i:i+batch_size] for i in range(0, len(texts), batch_size)]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {
                executor.submit(process_text_batch, batch): i 
                for i, batch in enumerate(text_batches)
            }
            
            for future in concurrent.futures.as_completed(future_to_batch):
                try:
                    batch_results = future.result()
                    results.extend(batch_results)
                    
                    # 更新进度
                    with task_lock:
                        processing_tasks[task_id]['completed'] += len(batch_results)
                        processing_tasks[task_id]['progress'] = (
                            processing_tasks[task_id]['completed'] / 
                            processing_tasks[task_id]['total'] * 100
                        )
                        
                except Exception as e:
                    with task_lock:
                        processing_tasks[task_id]['errors'].append(str(e))
        
        # 设置需要复核的数据
        if results and review_ratio > 0:
            review_count = max(1, int(len(results) * review_ratio))
            import random
            review_indices = random.sample(range(len(results)), review_count)
            for i in review_indices:
                results[i]['needs_review'] = True
        
        # 保存结果到数据库并创建版本
        existing_data = CachedDataLoader.load_data_with_cache()
        existing_data.extend(results)
        
        success = CachedDataLoader.save_data_with_cache(
            existing_data,
            operation="batch_process",
            description=f"批量处理 {len(results)} 条文本数据",
            user_id=task_id
        )
        
        # 保存结果
        with task_lock:
            processing_tasks[task_id]['status'] = 'completed' if success else 'failed'
            processing_tasks[task_id]['results'] = results
            if not success:
                processing_tasks[task_id]['error'] = '保存数据失败'
            
    except Exception as e:
        logger.error(f"批量处理失败: {e}")
        with task_lock:
            processing_tasks[task_id]['status'] = 'failed'
            processing_tasks[task_id]['error'] = str(e)

# 路由定义
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload')
def upload_page():
    return render_template('upload.html')

@app.route('/config')
def config_page():
    return render_template('config.html')

@app.route('/process')
def process_page():
    return render_template('process.html')

@app.route('/review')
def review_page():
    return render_template('review.html')

@app.route('/train')
def train_page():
    return render_template('train.html')

@app.route('/evaluate')
def evaluate_page():
    return render_template('evaluate.html')

@app.route('/export')
def export_page():
    return render_template('export.html')

@app.route('/versions')
def versions_page():
    return render_template('versions.html')

# API 端点
@app.route('/api/upload', methods=['POST'])
def upload_file():
    """文件上传接口"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': '没有选择文件'}), 400
        
        file = request.files['file']
        dataset_type = request.form.get('dataset_type', 'train')  # 数据集类型
        
        if file.filename == '':
            return jsonify({'error': '没有选择文件'}), 400
        
        if file:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # 解析文件
            texts = []
            file_ext = filename.lower().split('.')[-1]
            encoding = request.form.get('encoding', 'utf-8')
            
            if file_ext == 'csv':
                try:
                    df = pd.read_csv(file_path, encoding=encoding)
                    text_column = request.form.get('text_column', 'auto')
                    
                    if text_column == 'auto':
                        # 自动选择最可能的文本列
                        for col in df.columns:
                            if df[col].dtype == 'object' and df[col].str.len().mean() > 10:
                                text_column = col
                                break
                    else:
                        text_column = df.columns[int(text_column)]
                    
                    for _, row in df.iterrows():
                        text_content = str(row[text_column]).strip()
                        if text_content and text_content != 'nan':
                            texts.append({
                                'text': text_content, 
                                'source': 'csv',
                                'dataset_type': dataset_type,
                                'row_data': row.to_dict(),
                                'upload_time': datetime.now().isoformat()
                            })
                except Exception as e:
                    # 尝试其他编码
                    for fallback_encoding in ['gbk', 'gb2312', 'latin1']:
                        try:
                            df = pd.read_csv(file_path, encoding=fallback_encoding)
                            # 重复上面的逻辑
                            break
                        except:
                            continue
                    else:
                        raise e
                        
            elif file_ext == 'txt':
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        lines = f.readlines()
                        for i, line in enumerate(lines):
                            line = line.strip()
                            if line:
                                texts.append({
                                    'text': line, 
                                    'source': 'txt',
                                    'dataset_type': dataset_type,
                                    'line_number': i + 1,
                                    'upload_time': datetime.now().isoformat()
                                })
                except UnicodeDecodeError:
                    # 尝试其他编码
                    for fallback_encoding in ['gbk', 'gb2312', 'latin1']:
                        try:
                            with open(file_path, 'r', encoding=fallback_encoding) as f:
                                lines = f.readlines()
                                # 重复上面的逻辑
                                break
                        except:
                            continue
            else:
                return jsonify({'error': '不支持的文件格式'}), 400
            
            # 清理临时文件
            os.remove(file_path)
            
            return jsonify({
                'success': True,
                'count': len(texts),
                'texts': texts,
                'dataset_type': dataset_type,
                'encoding_used': encoding,
                'preview': texts[:50] if len(texts) > 50 else texts  # 返回前50条作为预览
            })
            
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        return jsonify({'error': f'文件处理失败: {str(e)}'}), 500

@app.route('/api/llm-config', methods=['GET', 'POST'])
def handle_llm_config():
    """LLM配置接口"""
    if request.method == 'GET':
        config = load_llm_config()
        return jsonify(config)
    
    elif request.method == 'POST':
        try:
            config = request.json
            # 验证配置
            required_fields = ['api_type', 'model_name']
            for field in required_fields:
                if field not in config:
                    return jsonify({'error': f'缺少必要字段: {field}'}), 400
            
            save_llm_config(config)
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/test-llm', methods=['POST'])
def test_llm():
    """测试LLM配置"""
    try:
        config = request.json
        llm_client = LLMClient(config)
        
        # 测试文本
        test_texts = ["这个产品很好用，值得推荐"]
        results = llm_client.predict_sentiment_batch(test_texts)
        
        return jsonify({
            'success': True,
            'result': results[0],
            'test_text': test_texts[0]
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/process-batch', methods=['POST'])
def process_batch():
    """批量处理接口"""
    try:
        data = request.json
        texts = data.get('texts', [])
        review_ratio = data.get('review_ratio', 0.1)
        
        if not texts:
            return jsonify({'error': '没有要处理的文本'}), 400
        
        # 创建任务ID
        task_id = str(uuid.uuid4())
        
        # 加载LLM配置
        llm_config = load_llm_config()
        
        # 启动后台处理
        thread = threading.Thread(
            target=process_batch_texts,
            args=(texts, task_id, llm_config, review_ratio)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'task_id': task_id
        })
        
    except Exception as e:
        logger.error(f"批量处理启动失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/task-status/<task_id>')
def get_task_status(task_id):
    """获取任务状态"""
    with task_lock:
        task = processing_tasks.get(task_id)
        if not task:
            return jsonify({'error': '任务不存在'}), 404
        return jsonify(task)

@app.route('/api/data', methods=['GET', 'POST'])
def handle_data():
    """数据管理接口"""
    ensure_data_file()
    
    if request.method == 'GET':
        data = CachedDataLoader.load_data_with_cache()
        return jsonify(data)
    
    elif request.method == 'POST':
        try:
            new_data = request.json
            
            existing_data = CachedDataLoader.load_data_with_cache()
            
            if isinstance(new_data, list):
                existing_data.extend(new_data)
                description = f"批量添加 {len(new_data)} 条数据"
            else:
                existing_data.append(new_data)
                description = "添加单条数据"
            
            success = CachedDataLoader.save_data_with_cache(
                existing_data,
                operation="data_add",
                description=description,
                user_id=request.headers.get('User-ID', 'api_user')
            )
            
            return jsonify({'success': success})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/data/<int:index>', methods=['PUT', 'DELETE'])
def handle_single_data(index):
    """单条数据操作接口"""
    try:
        data = CachedDataLoader.load_data_with_cache()
        
        if index < 0 or index >= len(data):
            return jsonify({'error': '数据索引无效'}), 400
        
        if request.method == 'PUT':
            # 更新数据
            update_data = request.json
            old_data = data[index].copy()
            data[index].update(update_data)
            data[index]['updated_time'] = datetime.now().isoformat()
            
            success = CachedDataLoader.save_data_with_cache(
                data,
                operation="data_update",
                description=f"更新第 {index+1} 条数据",
                user_id=request.headers.get('User-ID', 'api_user')
            )
            
            return jsonify({'success': success, 'old_data': old_data, 'new_data': data[index]})
        
        elif request.method == 'DELETE':
            # 删除数据
            deleted_data = data.pop(index)
            
            success = CachedDataLoader.save_data_with_cache(
                data,
                operation="data_delete",
                description=f"删除第 {index+1} 条数据",
                user_id=request.headers.get('User-ID', 'api_user')
            )
            
            return jsonify({'success': success, 'deleted_data': deleted_data})
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats')
def get_stats():
    """获取统计信息"""
    try:
        data = CachedDataLoader.load_data_with_cache()
        
        total = len(data)
        labeled = len([item for item in data if 'final_label' in item])
        needs_review = len([item for item in data if item.get('needs_review', False)])
        reviewed = len([item for item in data if item.get('reviewed', False)])
        
        positive = len([item for item in data if item.get('final_label') == 1])
        negative = len([item for item in data if item.get('final_label') == 0])
        
        # 数据集类型统计
        train_count = len([item for item in data if item.get('dataset_type') == 'train'])
        test_count = len([item for item in data if item.get('dataset_type') == 'test'])
        validation_count = len([item for item in data if item.get('dataset_type') == 'validation'])
        
        # 数据源统计
        source_stats = defaultdict(int)
        for item in data:
            source_stats[item.get('source', 'unknown')] += 1
        
        return jsonify({
            'total': total,
            'labeled': labeled,
            'needs_review': needs_review,
            'reviewed': reviewed,
            'positive': positive,
            'negative': negative,
            'train_count': train_count,
            'test_count': test_count,
            'validation_count': validation_count,
            'source_stats': dict(source_stats),
            'current_version': data_manager.current_version,
            'last_updated': data_cache.get('last_modified')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 新增版本控制API
@app.route('/api/versions', methods=['GET'])
def get_versions():
    """获取版本列表"""
    try:
        limit = request.args.get('limit', 50, type=int)
        versions = data_manager.get_version_list(limit)
        return jsonify({
            'success': True,
            'versions': versions,
            'current_version': data_manager.current_version
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/versions/<version_id>', methods=['GET'])
def get_version_data(version_id):
    """获取指定版本的数据"""
    try:
        data = data_manager.load_version(version_id)
        if data is None:
            return jsonify({'error': '版本不存在'}), 404
        
        return jsonify({
            'success': True,
            'version_id': version_id,
            'data': data,
            'count': len(data)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/versions/<version_id>/rollback', methods=['POST'])
def rollback_version(version_id):
    """回滚到指定版本"""
    try:
        user_id = request.headers.get('User-ID', 'api_user')
        success = data_manager.rollback_to_version(version_id, user_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'成功回滚到版本 {version_id}',
                'current_version': data_manager.current_version
            })
        else:
            return jsonify({'error': '回滚失败'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/versions/create', methods=['POST'])
def create_version():
    """手动创建版本"""
    try:
        request_data = request.json or {}
        description = request_data.get('description', '手动创建版本')
        user_id = request.headers.get('User-ID', 'api_user')
        
        data = CachedDataLoader.load_data_with_cache()
        version_id = data_manager.save_version(
            data,
            operation="manual_create",
            description=description,
            user_id=user_id
        )
        
        if version_id:
            return jsonify({
                'success': True,
                'version_id': version_id,
                'message': '版本创建成功'
            })
        else:
            return jsonify({'error': '版本创建失败'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/operation-history', methods=['GET'])
def get_operation_history():
    """获取操作历史"""
    try:
        limit = request.args.get('limit', 100, type=int)
        history = data_manager.get_operation_history(limit)
        
        return jsonify({
            'success': True,
            'history': history
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    """清除数据缓存"""
    try:
        data_manager.clear_cache()
        return jsonify({
            'success': True,
            'message': '缓存已清除'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/export-results', methods=['POST'])
def export_results():
    """导出分析结果"""
    try:
        data = request.json
        export_data = data.get('data', [])
        export_format = data.get('format', 'csv')
        export_type = data.get('type', 'all')  # all, labeled, unlabeled, needs_review
        include_fields = data.get('fields', [])
        
        if not export_data:
            # 从缓存加载数据
            export_data = CachedDataLoader.load_data_with_cache()
        
        # 过滤数据
        filtered_data = []
        for item in export_data:
            if export_type == 'labeled' and not item.get('final_label'):
                continue
            elif export_type == 'unlabeled' and item.get('final_label') is not None:
                continue
            elif export_type == 'needs_review' and not item.get('needs_review'):
                continue
            
            filtered_data.append(item)
        
        if not filtered_data:
            return jsonify({'error': '没有符合条件的数据可导出'}), 400
        
        # 准备导出数据
        export_rows = []
        for item in filtered_data:
            row = {
                '文本内容': item.get('text', ''),
                'LLM预测': '正面' if item.get('llm_prediction') == 1 else '负面' if item.get('llm_prediction') == 0 else '未预测',
                'LLM置信度': f"{item.get('llm_confidence', 0):.3f}",
                'LLM来源': item.get('llm_source', ''),
                'SnowNLP预测': '正面' if item.get('snownlp_prediction') == 1 else '负面' if item.get('snownlp_prediction') == 0 else '未预测',
                'SnowNLP置信度': f"{item.get('snownlp_confidence', 0):.3f}",
                '人工标注': '正面' if item.get('final_label') == 1 else '负面' if item.get('final_label') == 0 else '未标注',
                '需要复核': '是' if item.get('needs_review') else '否',
                '已复核': '是' if item.get('reviewed') else '否',
                '数据集类型': item.get('dataset_type', ''),
                '处理时间': item.get('timestamp', ''),
                '上传时间': item.get('upload_time', ''),
                '数据来源': item.get('source', '')
            }
            
            # 如果指定了特定字段，只导出这些字段
            if include_fields:
                row = {k: v for k, v in row.items() if k in include_fields}
            
            export_rows.append(row)
        
        # 生成文件
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if export_format == 'csv':
            filename = f'sentiment_analysis_{export_type}_{timestamp}.csv'
            filepath = os.path.join('exports', filename)
            
            df = pd.DataFrame(export_rows)
            df.to_csv(filepath, index=False, encoding='utf-8-sig')
            
            return send_file(filepath, as_attachment=True, download_name=filename)
            
        elif export_format == 'excel':
            filename = f'sentiment_analysis_{export_type}_{timestamp}.xlsx'
            filepath = os.path.join('exports', filename)
            
            df = pd.DataFrame(export_rows)
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='情感分析结果', index=False)
                
                # 添加统计信息
                stats = {
                    '总数据量': len(filtered_data),
                    '正面情感': len([x for x in filtered_data if x.get('final_label') == 1]),
                    '负面情感': len([x for x in filtered_data if x.get('final_label') == 0]),
                    '已标注': len([x for x in filtered_data if x.get('final_label') is not None]),
                    '需复核': len([x for x in filtered_data if x.get('needs_review')]),
                    '已复核': len([x for x in filtered_data if x.get('reviewed')]),
                    '数据版本': data_manager.current_version,
                    '导出时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                stats_df = pd.DataFrame(list(stats.items()), columns=['指标', '数值'])
                stats_df.to_excel(writer, sheet_name='统计信息', index=False)
            
            return send_file(filepath, as_attachment=True, download_name=filename)
            
        elif export_format == 'json':
            filename = f'sentiment_analysis_{export_type}_{timestamp}.json'
            filepath = os.path.join('exports', filename)
            
            export_obj = {
                'metadata': {
                    'export_time': datetime.now().isoformat(),
                    'export_type': export_type,
                    'total_count': len(filtered_data),
                    'fields': list(export_rows[0].keys()) if export_rows else [],
                    'data_version': data_manager.current_version,
                    'system_version': '2.0.0'
                },
                'data': export_rows
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_obj, f, ensure_ascii=False, indent=2)
            
            return send_file(filepath, as_attachment=True, download_name=filename)
            
        else:
            return jsonify({'error': '不支持的导出格式'}), 400
            
    except Exception as e:
        logger.error(f"导出失败: {e}")
        return jsonify({'error': f'导出失败: {str(e)}'}), 500

@app.route('/api/export-stats')
def get_export_stats():
    """获取可导出的数据统计"""
    try:
        data = CachedDataLoader.load_data_with_cache()
        
        stats = {
            'total': len(data),
            'labeled': len([item for item in data if item.get('final_label') is not None]),
            'unlabeled': len([item for item in data if item.get('final_label') is None]),
            'needs_review': len([item for item in data if item.get('needs_review')]),
            'reviewed': len([item for item in data if item.get('reviewed')]),
            'positive': len([item for item in data if item.get('final_label') == 1]),
            'negative': len([item for item in data if item.get('final_label') == 0]),
            'train_set': len([item for item in data if item.get('dataset_type') == 'train']),
            'test_set': len([item for item in data if item.get('dataset_type') == 'test']),
            'validation_set': len([item for item in data if item.get('dataset_type') == 'validation']),
            'current_version': data_manager.current_version,
            'last_updated': datetime.fromtimestamp(data_cache.get('last_modified', 0)).isoformat() if data_cache.get('last_modified') else None
        }
        
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"获取导出统计失败: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    ensure_data_file()
    app.run(debug=True, host='0.0.0.0', port=5000) 
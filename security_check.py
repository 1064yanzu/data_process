#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全检查脚本
用于验证API密钥配置和项目安全设置
"""

import os
import json
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

def print_status(message, status="info"):
    """打印带颜色的状态信息"""
    colors = {
        "success": "\033[92m✅",
        "warning": "\033[93m⚠️ ",
        "error": "\033[91m❌",
        "info": "\033[94mℹ️ "
    }
    reset = "\033[0m"
    print(f"{colors.get(status, colors['info'])} {message}{reset}")

def check_gitignore():
    """检查.gitignore文件配置"""
    print("\n🔍 检查.gitignore配置...")
    
    gitignore_path = Path('.gitignore')
    if not gitignore_path.exists():
        print_status(".gitignore文件不存在！", "error")
        return False
    
    with open(gitignore_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    required_patterns = [
        '.env',
        '*.env',
        'data/llm_config.json',
        '*.json',
        '*.db',
        '*.sqlite',
        'models/*.pkl'
    ]
    
    missing_patterns = []
    for pattern in required_patterns:
        if pattern not in content:
            missing_patterns.append(pattern)
    
    if missing_patterns:
        print_status(f"缺少以下保护模式: {', '.join(missing_patterns)}", "warning")
        return False
    else:
        print_status(".gitignore配置完整", "success")
        return True

def check_git_status():
    """检查git状态，确保敏感文件未被追踪"""
    print("\n🔍 检查Git状态...")
    
    try:
        # 检查是否在git仓库中
        result = subprocess.run(['git', 'status', '--porcelain'], 
                              capture_output=True, text=True, check=True)
        
        staged_files = result.stdout.strip().split('\n') if result.stdout.strip() else []
        sensitive_patterns = ['.env', 'config.env', 'llm_config.json', '.sqlite', '.db']
        
        sensitive_staged = []
        for line in staged_files:
            if line.strip():
                filename = line[3:].strip()  # 去掉git状态前缀
                for pattern in sensitive_patterns:
                    if pattern in filename:
                        sensitive_staged.append(filename)
        
        if sensitive_staged:
            print_status(f"发现敏感文件被Git追踪: {', '.join(sensitive_staged)}", "error")
            print("   请运行: git rm --cached <文件名> 来取消追踪")
            return False
        else:
            print_status("没有敏感文件被Git追踪", "success")
            return True
            
    except subprocess.CalledProcessError:
        print_status("不在Git仓库中或Git命令失败", "warning")
        return True
    except FileNotFoundError:
        print_status("未安装Git", "warning")
        return True

def check_env_file():
    """检查环境变量文件"""
    print("\n🔍 检查环境变量配置...")
    
    env_files = ['.env', 'config.env']
    env_found = False
    
    for env_file in env_files:
        if Path(env_file).exists():
            print_status(f"找到环境变量文件: {env_file}", "success")
            env_found = True
            
            # 检查文件内容
            with open(env_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 检查是否包含真实的API密钥
            if 'your_' in content or 'sk-your' in content:
                print_status(f"{env_file} 包含示例密钥，请填入真实密钥", "warning")
            else:
                print_status(f"{env_file} 配置看起来正常", "success")
    
    if not env_found:
        print_status("未找到环境变量文件，请创建 .env 文件", "warning")
        return False
    
    return env_found

def check_api_keys():
    """检查API密钥配置"""
    print("\n🔍 检查API密钥配置...")
    
    load_dotenv()
    
    api_keys = {
        'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY'),
        'QIANFAN_ACCESS_KEY': os.getenv('QIANFAN_ACCESS_KEY'),
        'DASHSCOPE_API_KEY': os.getenv('DASHSCOPE_API_KEY'),
        'TENCENT_SECRET_ID': os.getenv('TENCENT_SECRET_ID')
    }
    
    configured_keys = 0
    for key_name, key_value in api_keys.items():
        if key_value:
            if key_value.startswith('your_') or key_value.startswith('sk-your'):
                print_status(f"{key_name}: 包含示例值", "warning")
            else:
                print_status(f"{key_name}: 已配置 (长度: {len(key_value)})", "success")
                configured_keys += 1
        else:
            print_status(f"{key_name}: 未配置", "info")
    
    if configured_keys == 0:
        print_status("未配置任何API密钥", "warning")
        return False
    else:
        print_status(f"已配置 {configured_keys} 个API密钥", "success")
        return True

def check_sensitive_files():
    """检查敏感文件是否存在"""
    print("\n🔍 检查敏感文件...")
    
    sensitive_files = [
        'data/llm_config.json',
        'data/sentiment_db.sqlite',
        'api_keys.json',
        'secrets.json'
    ]
    
    found_files = []
    for file_path in sensitive_files:
        if Path(file_path).exists():
            found_files.append(file_path)
    
    if found_files:
        print_status(f"发现敏感文件: {', '.join(found_files)}", "info")
        print("   请确保这些文件在.gitignore中")
    else:
        print_status("未发现额外的敏感文件", "success")
    
    return True

def test_api_connection():
    """测试API连接"""
    print("\n🔍 测试API连接...")
    
    try:
        from app import load_llm_config, LLMClient
        
        config = load_llm_config()
        if not config.get('api_key'):
            print_status("未配置API密钥，跳过连接测试", "warning")
            return False
        
        # 测试简单的API调用
        client = LLMClient(config)
        # 这里可以添加实际的API测试代码
        print_status("API配置加载成功", "success")
        return True
        
    except Exception as e:
        print_status(f"API连接测试失败: {e}", "error")
        return False

def generate_report(results):
    """生成安全检查报告"""
    print("\n" + "="*50)
    print("🔐 安全检查报告")
    print("="*50)
    
    total_checks = len(results)
    passed_checks = sum(results.values())
    
    print(f"总检查项: {total_checks}")
    print(f"通过项目: {passed_checks}")
    print(f"成功率: {passed_checks/total_checks*100:.1f}%")
    
    if passed_checks == total_checks:
        print_status("\n🎉 所有安全检查通过！", "success")
    elif passed_checks >= total_checks * 0.8:
        print_status("\n✅ 安全配置基本完善，建议修复警告项", "warning")
    else:
        print_status("\n⚠️  存在安全风险，请修复错误项", "error")
    
    # 给出建议
    print("\n📋 建议操作:")
    if not results.get('gitignore', True):
        print("   1. 完善.gitignore文件配置")
    if not results.get('env_file', True):
        print("   2. 创建.env文件并配置API密钥")
    if not results.get('api_keys', True):
        print("   3. 配置真实的API密钥")
    if not results.get('git_status', True):
        print("   4. 清理Git中的敏感文件")

def main():
    """主函数"""
    print("🔐 情感分析系统 - 安全检查")
    print("="*50)
    
    results = {}
    
    # 执行各项检查
    results['gitignore'] = check_gitignore()
    results['git_status'] = check_git_status()
    results['env_file'] = check_env_file()
    results['api_keys'] = check_api_keys()
    results['sensitive_files'] = check_sensitive_files()
    results['api_connection'] = test_api_connection()
    
    # 生成报告
    generate_report(results)
    
    # 返回退出码
    success_rate = sum(results.values()) / len(results)
    sys.exit(0 if success_rate >= 0.8 else 1)

if __name__ == "__main__":
    main() 
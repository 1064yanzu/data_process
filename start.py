#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
情感分析助手启动脚本
自动初始化示例数据并启动应用
"""

import os
import json
import shutil
from app import app

def setup_sample_data():
    """设置示例数据"""
    sample_data_file = '示例数据.json'
    data_file = 'sentiment_data.json'
    
    if os.path.exists(sample_data_file) and not os.path.exists(data_file):
        print("正在设置示例数据...")
        shutil.copy(sample_data_file, data_file)
        print("示例数据设置完成！")
    else:
        print("使用现有数据文件")

def print_welcome():
    """打印欢迎信息"""
    print("=" * 60)
    print("🧠 情感分析助手 v1.0.0")
    print("=" * 60)
    print("📋 主要功能：")
    print("  • LLM 辅助情感数据标注")
    print("  • 自定义模型训练")
    print("  • 训练前后效果评估")
    print("  • 美观的可视化界面")
    print()
    print("🚀 访问地址：http://localhost:5000")
    print("📚 项目文档：README.md")
    print("🔧 技术文档：项目文档.md")
    print()
    print("💡 使用提示：")
    print("  1. 在数据标注页面添加文本进行标注")
    print("  2. 积累至少10条数据后可进行模型训练")
    print("  3. 在效果评估页面查看训练效果")
    print("=" * 60)
    print()

if __name__ == '__main__':
    print_welcome()
    setup_sample_data()
    
    print("正在启动应用...")
    print("按 Ctrl+C 停止服务器")
    print()
    
    try:
        app.run(debug=True, host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("\n👋 感谢使用情感分析助手！") 
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Git推送问题自动修复脚本
"""

import subprocess
import sys
import time
import os

def run_command(cmd, description=""):
    """运行命令并显示结果"""
    print(f"\n🔧 {description}")
    print(f"命令: {cmd}")
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(f"✅ 成功: {result.stdout.strip()}")
            return True
        else:
            print(f"❌ 失败: {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        print("⏰ 命令超时")
        return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def check_internet():
    """检查网络连接"""
    print("\n🌐 检查网络连接...")
    commands = [
        ("ping -n 2 github.com", "测试GitHub连接"),
        ("ping -n 2 gitee.com", "测试Gitee连接")
    ]
    
    results = []
    for cmd, desc in commands:
        success = run_command(cmd, desc)
        results.append(success)
    
    return any(results)

def fix_git_config():
    """修复Git配置"""
    print("\n⚙️ 优化Git配置...")
    
    configs = [
        ("git config --global http.postBuffer 524288000", "增加缓冲区大小"),
        ("git config --global http.lowSpeedLimit 0", "取消低速限制"),
        ("git config --global http.lowSpeedTime 999999", "增加超时时间"),
        ("git config --global core.compression 0", "禁用压缩"),
        ("git config --global http.sslVerify false", "临时禁用SSL验证（不推荐）")
    ]
    
    for cmd, desc in configs:
        run_command(cmd, desc)

def try_push_methods():
    """尝试不同的推送方法"""
    print("\n🚀 尝试推送到远程仓库...")
    
    # 检查是否有远程仓库
    result = subprocess.run("git remote -v", shell=True, capture_output=True, text=True)
    if not result.stdout.strip():
        print("❗ 没有配置远程仓库")
        print("\n请按照以下步骤操作：")
        print("1. 在GitHub上创建新仓库")
        print("2. 运行: git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git")
        print("3. 运行: git push -u origin main")
        return False
    
    # 尝试不同的推送方法
    push_commands = [
        ("git push origin main", "标准推送"),
        ("git push -f origin main", "强制推送"),
        ("git push --set-upstream origin main", "设置上游推送")
    ]
    
    for cmd, desc in push_commands:
        print(f"\n🔄 尝试{desc}...")
        success = run_command(cmd, desc)
        if success:
            print("🎉 推送成功！")
            return True
        
        print("⏳ 等待5秒后重试...")
        time.sleep(5)
    
    return False

def suggest_alternatives():
    """建议替代方案"""
    print("\n💡 替代方案建议：")
    print("="*50)
    
    print("1. 📁 手动上传方法：")
    print("   - 将项目打包成ZIP文件")
    print("   - 在GitHub网页版手动上传")
    
    print("\n2. 🔧 使用SSH方式：")
    print("   - ssh-keygen -t rsa -b 4096 -C 'your_email@example.com'")
    print("   - 将公钥添加到GitHub SSH设置")
    print("   - git remote set-url origin git@github.com:USERNAME/REPO.git")
    
    print("\n3. 🇨🇳 使用国内镜像：")
    print("   - git remote add gitee https://gitee.com/USERNAME/REPO.git")
    print("   - git push gitee main")
    
    print("\n4. 📱 使用移动热点：")
    print("   - 尝试使用手机热点")
    print("   - 可能绕过网络限制")
    
    print("\n5. ⏰ 错峰推送：")
    print("   - 尝试在网络使用较少的时间段推送")
    print("   - 如早晨或深夜")

def create_gitee_helper():
    """创建Gitee推送助手"""
    gitee_script = """@echo off
echo 正在推送到Gitee镜像...
git remote add gitee https://gitee.com/YOUR_USERNAME/sentiment-analysis.git
git push gitee main
echo 如果成功，请将YOUR_USERNAME替换为您的Gitee用户名
pause
"""
    
    with open("push_to_gitee.bat", "w", encoding="utf-8") as f:
        f.write(gitee_script)
    
    print("\n📝 已创建 push_to_gitee.bat 脚本")
    print("   修改其中的用户名后双击运行")

def main():
    """主函数"""
    print("🚀 Git推送问题自动修复工具")
    print("="*50)
    
    # 检查网络
    if not check_internet():
        print("❌ 网络连接有问题，请检查网络设置")
    
    # 修复Git配置
    fix_git_config()
    
    # 尝试推送
    if not try_push_methods():
        print("\n❌ 所有推送方法都失败了")
        suggest_alternatives()
        create_gitee_helper()
    
    print("\n" + "="*50)
    print("🔍 问题诊断完成")
    print("如果问题仍未解决，请尝试替代方案或联系技术支持")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n用户中断操作")
    except Exception as e:
        print(f"\n脚本执行出错: {e}")
    
    input("\n按回车键退出...") 
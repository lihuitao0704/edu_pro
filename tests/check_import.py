import sys
sys.path.insert(0, ".")

try:
    from main import app
    print("main.py 导入成功")
except Exception as e:
    print(f"导入失败: {e}")

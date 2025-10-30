"""
验证 user_subscribe_mail 表结构
"""
import sys
from pathlib import Path

# 添加父目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from database import engine


def verify_schema():
    """验证表结构"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            DESCRIBE user_subscribe_mail
        """))

        print("user_subscribe_mail 表结构：")
        print("-" * 80)
        for row in result:
            print(f"字段: {row[0]:<20} 类型: {row[1]:<20} 默认值: {row[4]}")
        print("-" * 80)


if __name__ == "__main__":
    verify_schema()

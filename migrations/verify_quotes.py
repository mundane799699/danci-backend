"""
验证金句表数据
"""
import sys
from pathlib import Path

# 添加父目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from database import engine


def verify_quotes():
    """验证金句数据"""
    with engine.connect() as conn:
        # 查询金句总数
        result = conn.execute(text("SELECT COUNT(*) FROM quotes"))
        total = result.scalar()

        print(f"金句表总数: {total} 条")
        print("\n前 5 条金句:")
        print("-" * 80)

        # 查询前5条金句
        result = conn.execute(text("SELECT id, content FROM quotes LIMIT 5"))
        for row in result:
            print(f"ID: {row[0]} | {row[1]}")

        print("-" * 80)


if __name__ == "__main__":
    verify_quotes()

"""
创建 quotes 金句表
运行此脚本以创建金句表
"""
import sys
from pathlib import Path

# 添加父目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from database import engine


def upgrade():
    """创建 quotes 表"""
    with engine.connect() as conn:
        # 检查表是否已存在
        result = conn.execute(text("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name='quotes'
        """))

        if result.scalar() == 0:
            # 创建 quotes 表
            conn.execute(text("""
                CREATE TABLE quotes (
                    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '金句ID',
                    content TEXT NOT NULL COMMENT '金句内容',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                    INDEX idx_id (id)
                ) COMMENT='金句表'
            """))
            conn.commit()
            print("✓ 成功创建 quotes 金句表")
        else:
            print("✓ quotes 表已存在，跳过创建")


def downgrade():
    """删除 quotes 表"""
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS quotes"))
        conn.commit()
        print("✓ 成功删除 quotes 表")


if __name__ == "__main__":
    print("开始创建金句表...")
    upgrade()
    print("金句表创建完成！")

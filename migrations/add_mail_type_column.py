"""
添加 mail_type 列到 user_subscribe_mail 表
运行此脚本以更新现有数据库
"""
import sys
from pathlib import Path

# 添加父目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from database import engine


def upgrade():
    """添加 mail_type 列"""
    with engine.connect() as conn:
        # 检查列是否已存在
        result = conn.execute(text("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name='user_subscribe_mail'
            AND column_name='mail_type'
        """))

        if result.scalar() == 0:
            # 添加 mail_type 列，默认值为 'word'
            conn.execute(text("""
                ALTER TABLE user_subscribe_mail
                ADD COLUMN mail_type VARCHAR(20) DEFAULT 'word'
                COMMENT '邮件类型：word-单词，quote-金句'
            """))
            conn.commit()
            print("✓ 成功添加 mail_type 列到 user_subscribe_mail 表")
        else:
            print("✓ mail_type 列已存在，跳过添加")


def downgrade():
    """移除 mail_type 列"""
    with engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE user_subscribe_mail
            DROP COLUMN IF EXISTS mail_type
        """))
        conn.commit()
        print("✓ 成功移除 mail_type 列")


if __name__ == "__main__":
    print("开始数据库迁移...")
    upgrade()
    print("数据库迁移完成！")

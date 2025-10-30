"""
创建 quote_email_history 金句邮件发送历史表
运行此脚本以创建金句邮件历史表
"""
import sys
from pathlib import Path

# 添加父目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from database import engine


def upgrade():
    """创建 quote_email_history 表"""
    with engine.connect() as conn:
        # 检查表是否已存在
        result = conn.execute(text("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name='quote_email_history'
        """))

        if result.scalar() == 0:
            # 创建 quote_email_history 表
            conn.execute(text("""
                CREATE TABLE quote_email_history (
                    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '历史记录ID',
                    user_id INT NOT NULL COMMENT '用户ID',
                    quote_id INT NOT NULL COMMENT '金句ID',
                    quote_content TEXT NOT NULL COMMENT '金句内容快照',
                    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '发送时间',
                    send_date VARCHAR(10) COMMENT '发送日期',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                    INDEX idx_user_id (user_id),
                    INDEX idx_user_date (user_id, send_date)
                ) COMMENT='金句邮件发送历史表'
            """))
            conn.commit()
            print("✓ 成功创建 quote_email_history 金句邮件历史表")
        else:
            print("✓ quote_email_history 表已存在，跳过创建")


def downgrade():
    """删除 quote_email_history 表"""
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS quote_email_history"))
        conn.commit()
        print("✓ 成功删除 quote_email_history 表")


if __name__ == "__main__":
    print("开始创建金句邮件历史表...")
    upgrade()
    print("金句邮件历史表创建完成！")

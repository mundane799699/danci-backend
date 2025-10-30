import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

import markdown2
from dotenv import load_dotenv
from models import (
    Quote,
    QuoteEmailHistory,
    UserSubscribeMail,
    Word,
    WordEmailHistory,
    WordEmailHistoryWord,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

load_dotenv()


class EmailService:
    def __init__(self):
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.sender_email = os.getenv("SENDER_EMAIL")
        self.sender_password = os.getenv("SENDER_PASSWORD")
        self.web_url = os.getenv("WEB_URL", "")

    def send_email(self, to_email: str, subject: str, content: str):
        try:
            msg = MIMEMultipart()
            msg["From"] = self.sender_email
            msg["To"] = to_email
            msg["Subject"] = subject

            msg.attach(MIMEText(content, "html"))

            # 创建SSL上下文
            context = ssl.create_default_context()

            # 使用SSL连接
            with smtplib.SMTP_SSL(
                self.smtp_server, self.smtp_port, context=context
            ) as server:
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"发送邮件失败: {str(e)}")
            return False

    def get_random_words(self, db: Session, count: int, user_id: int) -> List[dict]:
        """从数据库中随机获取指定数量的单词，排除用户已经背过的单词"""
        try:
            # 查询用户已经背过的单词ID
            learned_word_ids = (
                db.query(WordEmailHistoryWord.word_id)
                .join(
                    WordEmailHistory,
                    WordEmailHistoryWord.history_id == WordEmailHistory.id,
                )
                .filter(WordEmailHistory.user_id == user_id)
                .all()
            )
            learned_word_ids = [word_id[0] for word_id in learned_word_ids]

            # 使用ORDER BY RAND()实现随机获取，排除已学过的单词
            words = (
                db.query(Word)
                .filter(~Word.id.in_(learned_word_ids))
                .order_by(func.rand())
                .limit(count)
                .all()
            )

            # 将单词内容解析为字典格式
            result = []
            for word in words:
                result.append(
                    {"word": word.word, "content": word.content, "id": word.id}
                )
            return result
        except Exception as e:
            print(f"获取随机单词失败: {str(e)}")
            # 发生错误时返回空列表
            return []

    def process_content(self, content: str) -> str:
        """
        处理内容中的###标记，将其替换为**

        Args:
            content: 原始内容字符串

        Returns:
            str: 处理后的内容
        """
        # 按行分割内容
        lines = content.split("\n")

        # 处理每一行
        processed_lines = []
        for line in lines:
            # 检查是否包含"###"
            if "###" in line.strip() or "##" in line.strip():
                # 提取"###"以外的内容
                processed_content = line.replace("#", "").strip()
                # 返回加粗格式的内容
                processed_lines.append(f"**{processed_content}**")
            else:
                # 其他行保持不变
                processed_lines.append(line)

        # 重新组合行
        return "\n".join(processed_lines)

    def generate_email_content(self, words: List[dict]) -> str:
        # 邮件样式
        style = """
        <style>
            body {
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
            }
            h2 {
                color: #2c3e50;
                text-align: center;
                margin-bottom: 30px;
            }
            .word-card {
                border-radius: 8px;
                padding: 20px;
                margin-bottom: 30px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }
            .word-title {
                font-size: 24px;
                margin-bottom: 15px;
                text-align: center;
                font-weight: bold;
            }
            .separator {
                height: 1px;
                background-color: #9ca3af;
                margin: 15px 0;
            }
            h3 {
                color: #2c3e50;
                margin-top: 20px;
                margin-bottom: 10px;
            }
            p {
                margin: 10px 0;
            }
            ul, ol {
                padding-left: 20px;
            }
            li {
                margin: 5px 0;
            }
            .footer {
                text-align: center;
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #eee;
                color: #7f8c8d;
                font-size: 12px;
            }
            /* 背景颜色类 */
            .bg-amber-50 { background-color: #fffbeb; }
            .bg-pink-50 { background-color: #fdf2f8; }
            .bg-green-50 { background-color: #f0fdf4; }
            .bg-blue-50 { background-color: #eff6ff; }
            .bg-purple-50 { background-color: #faf5ff; }
            .bg-teal-50 { background-color: #f0fdfa; }
            .bg-indigo-50 { background-color: #eef2ff; }
            .bg-rose-50 { background-color: #fff1f2; }
        </style>
        """

        content = f"""
        <html>
            <head>
                {style}
            </head>
            <body>
                <p style="text-align: center; margin-bottom: 10px;">
                    <a href="{self.web_url}/dashboard/history-email" target="_blank" style="color: #3b82f6; text-decoration: underline;">查看网页端</a>
                </p>
                <h2>今天你背单词了吗？</h2>
        """

        # 定义背景颜色类
        background_colors = [
            "bg-amber-50",  # 米黄色
            "bg-pink-50",  # 浅粉色
            "bg-green-50",  # 浅绿色
            "bg-blue-50",  # 浅蓝色
            "bg-purple-50",  # 浅紫色
            "bg-teal-50",  # 浅青色
            "bg-indigo-50",  # 浅靛蓝色
            "bg-rose-50",  # 浅玫瑰色
        ]

        for word in words:
            # 使用单词ID作为种子来生成一致的随机颜色
            color_index = word["id"] % len(background_colors)
            bg_color = background_colors[color_index]

            # 处理内容中的###标记
            processed_content = self.process_content(word["content"])

            # 将Markdown转换为HTML
            html_content = markdown2.markdown(
                processed_content, extras=["fenced-code-blocks", "tables"]
            )

            content += f"""
                <div class="word-card {bg_color}">
                    <div class="word-title">{word["word"]}</div>
                    <div class="separator"></div>
                    {html_content}
                </div>
            """

        content += """
                <div class="footer">
                    <p>感谢订阅每日单词学习邮件！</p>
                    <p>如需取消订阅，请登录网站进行设置。</p>
                </div>
            </body>
        </html>
        """
        return content

    def handle_completed_user(
        self, db: Session, user_subscribe: UserSubscribeMail
    ) -> bool:
        """
        处理已完成所有单词学习的用户

        Args:
            db: 数据库会话
            user_subscribe: 用户订阅信息

        Returns:
            bool: 邮件发送是否成功
        """
        # 生成祝贺邮件内容
        congratulation_content = """
        <html>
        <body>
            <h2>恭喜您！</h2>
            <p>您已经完成了所有单词的学习！</p>
            <p>明天我们将重新开始，让您再次学习这些单词。</p>
            <p>感谢您使用我们的背单词服务！</p>
        </body>
        </html>
        """

        # 发送祝贺邮件
        subject = "恭喜您完成所有单词学习！"
        success = self.send_email(user_subscribe.email, subject, congratulation_content)

        # 如果发送成功，删除该用户的所有历史记录
        if success:
            try:
                # 删除用户的所有历史记录
                db.query(WordEmailHistory).filter(
                    WordEmailHistory.user_id == user_subscribe.user_id
                ).delete()
                db.commit()
                print(f"已删除用户 {user_subscribe.user_id} 的所有历史记录")
            except Exception as e:
                print(f"删除历史记录失败: {str(e)}")
                db.rollback()

        return success

    def send_word_email(self, db: Session, user_subscribe: UserSubscribeMail):
        words = self.get_random_words(
            db, user_subscribe.word_count, user_subscribe.user_id
        )

        # 检查是否获取到单词
        if not words:
            # 处理已完成所有单词的用户
            return self.handle_completed_user(db, user_subscribe)

        # 正常处理单词列表
        content = self.generate_email_content(words)
        subject = "每日邮件单词"

        # 发送邮件
        success = self.send_email(user_subscribe.email, subject, content)

        # 如果发送成功，记录历史
        if success:
            # 创建一条历史记录
            history = WordEmailHistory(
                user_id=user_subscribe.user_id,
                sent_at=func.now(),
                send_date=func.date(func.now()),
            )
            db.add(history)
            db.flush()  # 获取history.id

            # 为每个单词创建关联记录
            for word in words:
                history_word = WordEmailHistoryWord(
                    history_id=history.id, word_id=word["id"]
                )
                db.add(history_word)

            db.commit()

        return success

    def get_random_quote(self, db: Session, user_id: int) -> dict:
        """从数据库中随机获取一条金句，排除用户已经收到的金句"""
        try:
            # 1. 查询用户已经收到的金句ID列表
            sent_quote_ids = (
                db.query(QuoteEmailHistory.quote_id)
                .filter(QuoteEmailHistory.user_id == user_id)
                .all()
            )
            sent_quote_ids = [qid[0] for qid in sent_quote_ids]

            # 2. 从未发送过的金句中随机选择
            quote = (
                db.query(Quote)
                .filter(~Quote.id.in_(sent_quote_ids))
                .order_by(func.rand())
                .first()
            )

            # 3. 如果所有金句都已发送，清空历史重新开始
            if not quote:
                print(f"用户 {user_id} 已完成所有金句，清空历史重新开始")
                # 删除该用户的所有金句历史
                db.query(QuoteEmailHistory).filter(
                    QuoteEmailHistory.user_id == user_id
                ).delete()
                db.commit()

                # 重新随机选择
                quote = db.query(Quote).order_by(func.rand()).first()

            if quote:
                return {"content": quote.content, "id": quote.id}
            return None
        except Exception as e:
            print(f"获取随机金句失败: {str(e)}")
            return None

    def generate_quote_email_content(self, quote: dict) -> str:
        """生成金句邮件内容"""
        # 邮件样式
        style = """
        <style>
            body {
                font-family: 'Arial', 'Microsoft YaHei', sans-serif;
                line-height: 1.8;
                color: #333;
                max-width: 600px;
                margin: 0 auto;
                padding: 40px 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }
            .container {
                background: white;
                border-radius: 16px;
                padding: 40px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            }
            .header {
                text-align: center;
                margin-bottom: 30px;
            }
            .header h2 {
                color: #667eea;
                font-size: 24px;
                margin: 0;
                font-weight: 600;
            }
            .quote-container {
                background: linear-gradient(135deg, #fdfbfb 0%, #ebedee 100%);
                border-radius: 8px;
                padding: 30px;
                margin: 30px 0;
                position: relative;
            }
            .quote-mark {
                font-size: 60px;
                color: #667eea;
                opacity: 0.3;
                position: absolute;
                top: 10px;
                left: 20px;
                font-family: Georgia, serif;
            }
            .quote-content {
                font-size: 20px;
                line-height: 1.8;
                color: #2c3e50;
                text-align: center;
                padding: 20px 0;
                position: relative;
                z-index: 1;
                font-weight: 500;
            }
            .footer {
                text-align: center;
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #eee;
                color: #7f8c8d;
                font-size: 12px;
            }
            .divider {
                height: 2px;
                background: linear-gradient(to right, transparent, #667eea, transparent);
                margin: 20px 0;
            }
        </style>
        """

        content = f"""
        <html>
            <head>
                {style}
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>✨ 每日金句 ✨</h2>
                    </div>
                    <div class="divider"></div>
                    <div class="quote-container">
                        <div class="quote-content">
                            {quote["content"]}
                        </div>
                    </div>
                    <div class="divider"></div>
                    <div class="footer">
                        <p>愿这句话能为你带来力量与温暖</p>
                        <p>感谢订阅每日金句邮件！</p>
                        <p>如需取消订阅，请登录<a href="{self.web_url}/dashboard/email-settings" target="_blank" style="color: #667eea; text-decoration: underline;">进行设置</a>。</p>
                    </div>
                </div>
            </body>
        </html>
        """
        return content

    def send_quote_email(self, db: Session, user_subscribe: UserSubscribeMail):
        """发送金句邮件"""
        quote = self.get_random_quote(db, user_subscribe.user_id)

        # 检查是否获取到金句
        if not quote:
            print("未能获取到金句")
            return False

        # 生成邮件内容
        content = self.generate_quote_email_content(quote)
        subject = "每日金句"

        # 发送邮件
        success = self.send_email(user_subscribe.email, subject, content)

        # 如果发送成功，记录历史
        if success:
            # 创建一条历史记录
            history = QuoteEmailHistory(
                user_id=user_subscribe.user_id,
                quote_id=quote["id"],
                quote_content=quote["content"],
                sent_at=func.now(),
                send_date=func.date(func.now()),
            )
            db.add(history)
            db.commit()

        return success

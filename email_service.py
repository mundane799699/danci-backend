import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from models import UserSubscribeMail, Word, WordEmailHistory
import random
from typing import List
import os
from dotenv import load_dotenv
import ssl
import markdown2

load_dotenv()

class EmailService:
    def __init__(self):
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.sender_email = os.getenv("SENDER_EMAIL")
        self.sender_password = os.getenv("SENDER_PASSWORD")

    def send_email(self, to_email: str, subject: str, content: str):
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = to_email
            msg['Subject'] = subject

            msg.attach(MIMEText(content, 'html'))

            # 创建SSL上下文
            context = ssl.create_default_context()
            
            # 使用SSL连接
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context) as server:
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
            learned_word_ids = db.query(WordEmailHistory.word_id).filter(
                WordEmailHistory.user_id == user_id
            ).all()
            learned_word_ids = [word_id[0] for word_id in learned_word_ids]
            
            # 使用ORDER BY RAND()实现随机获取，排除已学过的单词
            words = db.query(Word).filter(
                ~Word.id.in_(learned_word_ids)
            ).order_by(func.rand()).limit(count).all()
            
            # 将单词内容解析为字典格式
            result = []
            for word in words:
                result.append({
                    "word": word.word,
                    "content": word.content,
                    "id": word.id
                })
            return result
        except Exception as e:
            print(f"获取随机单词失败: {str(e)}")
            # 发生错误时返回空列表
            return []

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
                background-color: #f9f9f9;
                border-radius: 8px;
                padding: 20px;
                margin-bottom: 30px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }
            .word-title {
                color: #3498db;
                font-size: 24px;
                margin-bottom: 15px;
                border-bottom: 2px solid #3498db;
                padding-bottom: 5px;
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
        </style>
        """
        
        content = f"""
        <html>
            <head>
                {style}
            </head>
            <body>
                <h2>今天背单词了吗？</h2>
        """
        
        for word in words:
            # 将Markdown转换为HTML
            html_content = markdown2.markdown(word['content'], extras=['fenced-code-blocks', 'tables'])
            
            content += f"""
                <div class="word-card">
                    <div class="word-title">{word['word']}</div>
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

    def handle_completed_user(self, db: Session, user_subscribe: UserSubscribeMail) -> bool:
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
        words = self.get_random_words(db, user_subscribe.word_count, user_subscribe.user_id)
        
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
            for word in words:
                # todo:每次发送邮件历史表只记录一条数据，另外再增加一张历史和单词关联表，将单词数据记录到关联表中
                history = WordEmailHistory(
                    user_id=user_subscribe.user_id,
                    word_id=word['id'],
                    sent_at=func.now(),
                    send_date=func.date(func.now())
                )
                db.add(history)
            db.commit()
            
        return success 
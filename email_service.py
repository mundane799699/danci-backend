import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import UserSubscribeMail, Word
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

    def get_random_words(self, db: Session, count: int) -> List[dict]:
        """从数据库中随机获取指定数量的单词"""
        try:
            # 使用ORDER BY RAND()实现随机获取
            words = db.query(Word).order_by(func.rand()).limit(count).all()
            
            # 将单词内容解析为字典格式
            result = []
            for word in words:
                result.append({
                    "word": word.word,
                    "content": word.content
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
                <h2>今天背单词了吗</h2>
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

    def send_word_email(self, db: Session, user_subscribe: UserSubscribeMail):
        words = self.get_random_words(db, user_subscribe.word_count)
        content = self.generate_email_content(words)
        subject = "每日邮件单词"
        return self.send_email(user_subscribe.email, subject, content) 
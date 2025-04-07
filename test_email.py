from email_service import EmailService
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def test_email_sending():
    # 创建邮件服务实例
    email_service = EmailService()
    
    # 测试邮件内容
    test_content = """
    <html>
        <body>
            <h2>测试邮件</h2>
            <p>这是一封测试邮件，用于验证邮件发送功能是否正常工作。</p>
            <table border="1" cellpadding="5" cellspacing="0">
                <tr>
                    <th>单词</th>
                    <th>翻译</th>
                </tr>
                <tr>
                    <td>test</td>
                    <td>测试</td>
                </tr>
            </table>
        </body>
    </html>
    """
    
    # 发送测试邮件
    result = email_service.send_email(
        to_email="799699348@qq.com",  # 替换为你的测试邮箱
        subject="邮件发送测试",
        content=test_content
    )
    
    if result:
        print("邮件发送成功！")
    else:
        print("邮件发送失败！")

if __name__ == "__main__":
    test_email_sending() 
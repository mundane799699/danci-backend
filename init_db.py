from database import engine
from models import Base

def init_db():
    # 创建所有表
    Base.metadata.create_all(bind=engine)
    print("数据库表创建完成！")

if __name__ == "__main__":
    print("开始创建数据库表...")
    init_db() 
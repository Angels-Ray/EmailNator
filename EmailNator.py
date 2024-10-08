import logging
from typing import Dict, List, Optional, Callable
import requests
from bs4 import BeautifulSoup
from functools import wraps
from urllib.parse import unquote

# 固定的 User-Agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

logger = logging.getLogger(__name__)


def error_handler(max_retries=3):
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            for retry_count in range(max_retries):
                try:
                    return func(self, *args, **kwargs)
                except requests.HTTPError as e:
                    if "419" in str(e):
                        print(f"捕获到 419 错误，重新获取 CSRF 令牌并重试: {e}")
                        self._initialize_session()
                    else:
                        print(f"网络请求出错: {e}")
                        break
                except Exception as e:
                    print(f"发生错误: {e}")
                    break
            return None
        return wrapper
    return decorator


class EmailNatorClient:
    def __init__(self, log_level=logging.INFO):
        self.base_url = "https://www.emailnator.com"
        self.session = requests.Session()
        self.xsrf_token = None
        
        self.logger = logging.getLogger(f"{__name__}.EmailNatorClient")
        self.logger.setLevel(log_level)
        
        self._initialize_session()

    def _initialize_session(self):
        try:
            self._make_request('get', self.base_url)
            self.logger.info("会话初始化成功")
        except Exception as e:
            self.logger.error(f"会话初始化失败: {e}")

    def _update_xsrf_token(self, cookies):
        self.xsrf_token = unquote(cookies.get('XSRF-TOKEN', ''))

    @staticmethod
    def _is_premium_email(email, num=2):
        """ 
        @description 检测邮箱质量
        @param email: email address
        @param num: 邮箱前缀可分隔的数量
        """
        parts_by_dot = email.split('.')
        parts_by_plus = [part.split('+') for part in parts_by_dot]
        all_parts = [part for sublist in parts_by_plus for part in sublist]
        return len(all_parts) <= num + 1

    @error_handler(max_retries=3)
    def _make_request(self, method, url, data=None):
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Xsrf-Token": self.xsrf_token
        }

        if method.lower() == 'post':
            headers.update({
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
            })
            response = self.session.post(url, headers=headers, json=data)
        else:
            headers.update({
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
            })
            response = self.session.get(url, headers=headers)

        response.raise_for_status()
        self._update_xsrf_token(self.session.cookies.get_dict())
        return response

    def generate_email(self, email_types: List[str] = ["plusGmail", "dotGmail", "googleMail"]) -> Optional[str]:
        """ 
        @description 生成邮箱地址
        @param email_types: 邮箱类型列表，默认为 ["plusGmail", "dotGmail", "googleMail"]
        @return str 或 None: 生成的邮箱地址，如果生成失败则返回 None

        示例:
        >>> client.generate_email()
        'test@gmail.com'
        """
        url = f"{self.base_url}/generate-email"
        data = {"email": email_types}
        response = self._make_request('post', url, data=data)
        return response.json().get("email", [None])[0] if response else None

    def generate_premium_email(self, max_attempts: int = 20, num: int = 2, email_type: List[str] = ["dotGmail", "googleMail"]) -> Optional[str]:
        """
        @description 生成优质邮箱地址
        @param max_attempts: 最大尝试次数
        @param num: 邮箱前缀可分隔的数量
        @param email_type: 邮箱类型列表, 默认为 ["dotGmail", "googleMail"]
        @return str 或 None: 生成的优质邮箱地址，如果生成失败则返回 None
        """
        for attempt in range(1, max_attempts + 1):
            email = self.generate_email(email_type)
            if email and self._is_premium_email(email, num):
                self.logger.info(f"成功生成优质邮箱: {email}")
                return email
            self.logger.debug(f"生成优质邮箱中, 尝试次数: {attempt}")
        self.logger.warning(f"未能在 {max_attempts} 次尝试内生成优质邮箱")
        return None

    def get_message_list(self, email: str) -> List[dict]:
        """ 
        @description 获取所有邮件列表
        @param email: 邮箱地址
        @return List[dict]: 邮件列表，每个邮件是一个字典

        示例返回值:
        [{'messageID': 'XXXXX==', 'from': 'Name <test@qq.com>', 'subject': 'test@googlemail.com', 'time': 'Just Now'}]
        """
        url = f"{self.base_url}/message-list"
        data = {"email": email}
        response = self._make_request('post', url, data)
        return [msg for msg in response.json().get("messageData", []) if "@" in msg["from"]] if response else []

    def get_new_message(self, email: str, callback: Optional[Callable] = None) -> dict:
        """ 
        @description 获取新邮件
        @param email: 邮箱地址
        @param callback: 可选的回调函数，用于处理新邮件
        @return dict: 新邮件信息，如果没有新邮件则返回空字典

        示例返回值:
        {'messageID': 'XXXXX==', 'from': 'Name <test@qq.com>', 'subject': 'test@googlemail.com', 'time': 'Just Now'}
        """
        message_list = self.get_message_list(email)
        for msg in message_list:
            if msg.get('time', '') == 'Just Now':
                self.logger.info(f"收到新邮件: {msg['subject']}")
                if callback is not None:
                    callback(msg)
                return msg
        self.logger.debug("没有新邮件")
        if callback is not None:
            callback({})
        return {}

    def get_email_content(self, email: str, message_id: str) -> dict:
        """ 
        @description 获取邮件内容
        @param email: 邮箱地址
        @param message_id: 邮件ID
        @return dict: 邮件详细内容

        示例返回值:
        {'from': 'test@gmail.com', 'subject': 'Test Subject', 'time': 'Just Now', 'body': 'Test Body'}
        """
        url = f"{self.base_url}/message-list"
        data = {"email": email, "messageID": message_id}
        response = self._make_request('post', url, data)
        return self._parse_email_content(response.text) if response else {}

    @staticmethod
    def _parse_email_content(content: str) -> Dict[str, str]:
        """ 解析邮件内容 """
        soup = BeautifulSoup(content, 'html.parser')
        header = soup.find(id="subject-header")
        email_details = {
            "from": header.find_all('b')[0].next_sibling.strip(),
            "subject": header.find_all('b')[1].next_sibling.strip(),
            "time": header.find_all('b')[2].next_sibling.strip(),
            "body": content.split('<hr /></div></div>', 1)[-1].strip() if '<hr /></div></div>' in content else ''
        }
        return email_details


def example_usage():
    import time
    # 创建EmailNatorClient实例
    client = EmailNatorClient()

    # 生成临时邮箱
    email_address = client.generate_premium_email()
    print("生成的邮箱:", email_address)

    def msg_callback(msg):
        print("新邮件:", msg)
        if msg:
            message_id = msg['messageID']
            email_content = client.get_email_content(email_address, message_id)
            print("邮件内容:", email_content)

    if email_address:
        while True:
            try:
                new_message = client.get_new_message(
                    email_address, msg_callback)
            except Exception as e:
                print(f"发生错误: {e}")
            time.sleep(5)
    else:
        print("未能生成邮箱地址")

# 如果想直接运行这个示例，可以取消下面的注释
# if __name__ == "__main__":
#     example_usage()

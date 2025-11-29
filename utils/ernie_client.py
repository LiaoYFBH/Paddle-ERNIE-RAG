import os
from openai import OpenAI
import time 
import logging
import random
import requests
import json
import base64
# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ernie_client")

class ERNIEClient:
    """
    百度 ERNIE / OpenAI 兼容客户端
    已更新：针对千帆原生 API 的 429 限流做深度优化
    """
    
    def __init__(self, 
                 llm_api_base=None, llm_api_key=None, llm_model=None,
                 embed_api_base=None, embed_api_key=None, embed_model=None,
                 qps=0.8): # 🌟 默认 QPS 调低至 0.8，更安全
        
        # === 1. LLM 配置 ===
        self.llm_base = (llm_api_base or "https://aistudio.baidu.com/llm/lmapi/v3").rstrip('/')
        self.llm_key = llm_api_key or os.getenv("AISTUDIO_ACCESS_TOKEN", "")
        self.chat_model_name = llm_model or "ernie-4.5-turbo-vl"#"ernie-4.5-turbo-128k-preview"
        
        # === 2. Embedding 配置 ===
        self.embed_base = (embed_api_base or "https://aistudio.baidu.com/llm/lmapi/v3").rstrip('/')
        self.embed_key = embed_api_key or os.getenv("AISTUDIO_ACCESS_TOKEN", "")
        self.embedding_model_name = embed_model or "embedding-v1"

        # === 4. 速率控制 ===
        self.target_qps = float(qps) if qps > 0 else 0.8
        self.current_delay = 1.0 / self.target_qps 
        
        self.last_embed_time = 0
        self.last_chat_time = 0
        self.max_retries = 5 # 最大重试次数
        
        # === 5. 初始化客户端 ===
        self.chat_client = None
        self.embed_client = None
        self._init_clients()

    def _init_clients(self):
        """初始化 OpenAI 客户端 (仅当不是千帆原生模式时)"""
        if self.llm_key:
            try:
                self.chat_client = OpenAI(base_url=self.llm_base, api_key=self.llm_key, max_retries=self.max_retries, timeout=120.0)
            except Exception as e: logger.error(f"❌ LLM Client 初始化异常: {e}")

        if self.embed_key:
            try:
                self.embed_client = OpenAI(base_url=self.embed_base, api_key=self.embed_key, max_retries=self.max_retries, timeout=120.0)
            except Exception as e: logger.error(f"❌ Embedding Client 初始化异常: {e}")
    def _encode_image(self, image_path):
            """辅助：读取图片并转 Base64"""
            try:
                with open(image_path, "rb") as image_file:
                    return base64.b64encode(image_file.read()).decode('utf-8')
            except Exception as e:
                # 如果读图失败，打日志，返回 None
                print(f"❌ 图片读取/编码失败: {e}") 
                return None

    def chat_with_image(self, query: str, image_path: str):
        """
        发送带图片的对话请求 (Vision)
        """
        base64_image = self._encode_image(image_path)
        
        # 1. 编码失败，降级
        if not base64_image:
            print("⚠️ 图片编码失败，降级为纯文本问答")
            return self.chat([{"role": "user", "content": query}])
        
        # 2. 构造 Vision 消息
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": query},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ]
        
        # 3. 尝试发送，并捕获特定错误
        try:
            return self.chat(messages)
        except Exception as e:
            # 抛出异常供上层 (backend.py) 捕获和处理
            raise e
    def _wait_for_rate_limit(self, is_embedding=True):
        """流控等待"""
        now = time.time()
        last_time = self.last_embed_time if is_embedding else self.last_chat_time
        elapsed = now - last_time
        if elapsed < self.current_delay:
            time.sleep(self.current_delay - elapsed)
        
        # 更新时间戳
        if is_embedding: self.last_embed_time = time.time()
        else: self.last_chat_time = time.time()

    def _adaptive_slow_down(self):
        """触发自适应降级：遇到限流时，永久增加间隔"""
        self.current_delay = min(self.current_delay * 2.0, 15.0) 
        logger.warning(f"📉 触发速率限制(429)，系统自动降速: 新间隔 {self.current_delay:.2f}s")

    def chat(self, messages: list, model=None, max_tokens=2048, temperature=0.7):
        use_model = model if model else self.chat_model_name
        self._wait_for_rate_limit(is_embedding=False)

        if not self.chat_client: return "错误: Client 未初始化"
        
        try:
            response = self.chat_client.chat.completions.create(
                model=use_model, messages=messages, max_tokens=max_tokens, temperature=temperature
            )
            self.last_chat_time = time.time()
            content = response.choices[0].message.content
            if not content: return "模型返回内容为空"
            return content
            
        except Exception as e:
            # 🛑 关键：不要在这里只打印日志然后返回 None/Str
            # 我们需要把原始错误 raise 出去，或者返回一个带有特殊标记的错误对象
            # 为了简单，我们这里 raise，让 backend 去 try-catch
            logger.error(f"❌ Chat 失败: {e}")
            raise e

    def get_embedding(self, text: str, max_retries: int = 5) -> list:
        if not text: return None
            
        for attempt in range(max_retries):
            try:
                self._wait_for_rate_limit(is_embedding=True)
                
                # === 分支 B: OpenAI 兼容模式 ===
                if self.embed_client:
                    response = self.embed_client.embeddings.create(
                        model=self.embedding_model_name, input=[text]
                    )
                    self.last_embed_time = time.time()
                    if response and response.data:
                        return response.data[0].embedding

            except Exception as e:
                error_str = str(e).lower()
                
                # 🌟 核心逻辑：识别千帆特定的限流错误码
                is_rate_limit = (
                    "429" in error_str or 
                    "rate limit" in error_str or 
                    "rpm_rate_limit_exceeded" in error_str or
                    "tpm_rate_limit_exceeded" in error_str
                )
                
                if is_rate_limit:
                    self._adaptive_slow_down() # 永久降速
                    
                    # 本次避让 (指数退避)
                    wait_time = (2 ** attempt) + random.uniform(1.0, 3.0)
                    logger.warning(f"⚠️ 触发限流保护，避让 {wait_time:.1f}s (尝试 {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    logger.warning(f"⚠️ Embedding 异常 (尝试 {attempt + 1}): {e}")
                    time.sleep(1)
        
        logger.error("❌ Embedding 最终失败")
        return None

    def get_embeddings(self, texts: list) -> list:
        """批量获取"""
        if not texts: return []
        results = []
        for t in texts:
            emb = self.get_embedding(t)
            results.append(emb)
        return results
    
    get_embeddings_batch = get_embeddings

    def answer_question(self, question: str, context_chunks: list) -> str:
        if not context_chunks:
            prompt = f"用户问题：{question}"
        else:
            context_str = ""
            for i, chunk in enumerate(context_chunks):
                content = chunk.get('content', '').replace('\n', ' ')[:800]
                fname = chunk.get('filename', '未知文档')
                page = chunk.get('page', 0)
                context_str += f"[参考资料{i+1} ({fname} P{page})]: {content}\n\n"
            prompt = f"基于以下参考资料回答问题：\n\n[参考资料]:\n{context_str}\n\n[用户问题]:\n{question}"
        return self.chat([{"role": "user", "content": prompt}]) or "生成回答失败"

    def generate_summary(self, text: str) -> str:
        if not text: return "无内容"
        prompt = f"请对以下文档内容生成一份精简摘要（200字以内）：\n\n{text[:5000]}"
        return self.chat([{"role": "user", "content": prompt}]) or "摘要生成失败"

    def rewrite_query(self, query: str) -> str:
        prompt = f"""请将以下搜索查询重写为一个更详细、包含更多上下文关键词的陈述句，以便于向量检索。
        
        原始查询: "{query}"
        重写后:"""
        res = self.chat([{"role": "user", "content": prompt}], max_tokens=200)
        return res if res else query
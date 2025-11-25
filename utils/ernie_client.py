import os
from openai import OpenAI
import time 
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ernie_client")

class ERNIEClient:
    """
    百度 ERNIE API 客户端 - 基于 OpenAI SDK 适配
    已修复：属性缺失、方法不全、重试机制
    """
    
    def __init__(self):
        # 1. 基础配置
        self.host_url = "https://aistudio.baidu.com/llm/lmapi/v3"
        self.api_key = os.getenv("AISTUDIO_ACCESS_TOKEN")
        
        # 2. 模型配置
        self.embedding_model = "embedding-v1"       # 默认嵌入模型
        self.chat_model = "ernie-4.5-turbo-128k-preview" # 默认对话模型
        
        # 3. 评测模式检查
        self.is_eval_mode = os.getenv("EVAL_MODE", "false").lower() == "true"
        if self.is_eval_mode:
            logger.info("ERNIEClient: 正在以“评测模式”启动 (启用 3 秒冷却)")
            self.sleep_time = 3.0
            self.max_retries = 1
        else:
            logger.info("ERNIEClient: 正在以“UI 模式”启动 (无冷却)")
            self.sleep_time = 0
            self.max_retries = 3 

        # 4. 速率控制
        self.call_delay = float(os.environ.get("ERNIE_CALL_DELAY", "1.5"))
        self.last_call_time = 0
        
        # 5. 初始化客户端 (带空值检查)
        self.client = None
        self._init_client()

    def _init_client(self):
        """初始化 OpenAI 客户端"""
        if not self.api_key:
            logger.warning("⚠️ 未检测到 AISTUDIO_ACCESS_TOKEN")
            return

        try:
            self.client = OpenAI(
                base_url=self.host_url,
                api_key=self.api_key,
                max_retries=self.max_retries,
                timeout=120.0
            )
            logger.info(f"✅ ERNIE Client 初始化成功")
        except Exception as e:
            logger.error(f"❌ 初始化异常: {e}")

    def chat(self, messages: list, model=None, max_tokens=2048, temperature=0.7):
        """
        通用聊天接口 (带速率控制)
        """
        if not self.client:
            # (应对环境变量后加载的情况)
            self.api_key = os.getenv("AISTUDIO_ACCESS_TOKEN")
            self._init_client()
            if not self.client:
                logger.error("Client 未就绪")
                return None

        # 使用默认模型或指定模型
        use_model = model if model else self.chat_model

        # 速率控制
        elapsed = time.time() - self.last_call_time
        if elapsed < self.call_delay:
            time.sleep(self.call_delay - elapsed)
        
        try:
            response = self.client.chat.completions.create(
                model=use_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            self.last_call_time = time.time()
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"❌ Chat 调用失败: {e}")
            self.last_call_time = time.time()
            return None 

    def get_embedding(self, text: str, max_retries: int = 3) -> list:
        """
        获取单个文本的 embedding (带重试)
        """
        if not self.client:
            self.api_key = os.getenv("AISTUDIO_ACCESS_TOKEN")
            self._init_client()
            if not self.client:
                logger.error("Client 未就绪，无法获取 Embedding")
                return None

        if not text or not isinstance(text, str):
            return None
            
        for attempt in range(max_retries):
            try:
                if self.is_eval_mode:
                    time.sleep(self.sleep_time)
                
                response = self.client.embeddings.create(
                    model=self.embedding_model,
                    input=[text]
                )
                
                if response and response.data:
                    return response.data[0].embedding
                
            except Exception as e:
                logger.warning(f"Embedding 失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
        
        logger.error("Embedding 最终失败")
        return None

    def get_embeddings(self, texts: list) -> list:
        """
        批量获取 (兼容 vector_store 调用)
        """
        if not texts: return []
        results = []
        for t in texts:
            # 串行调用以保证稳定性，避免触发并发限制
            emb = self.get_embedding(t)
            if emb:
                results.append(emb)
            else:
                # 保持列表长度对齐，失败填 None (或者根据需求填全0向量)
                results.append(None) 
        return results
    
    get_embeddings_batch = get_embeddings

    def answer_question(self, question: str, context_chunks: list) -> str:
        """
        RAG 问答生成
        """
        if not context_chunks:
            prompt = f"用户问题：{question}"
        else:
            context_str = ""
            for i, chunk in enumerate(context_chunks):
                # 简单的截断防止超长
                content = chunk.get('content', '').replace('\n', ' ')[:800]
                fname = chunk.get('filename', '未知文档')
                page = chunk.get('page', 0)
                context_str += f"[参考资料{i+1} ({fname} P{page})]: {content}\n\n"
            
            prompt = f"""基于以下参考资料回答问题。如果资料中没有答案，请根据你的知识回答但需注明。

[参考资料]:
{context_str}

[用户问题]:
{question}"""

        return self.chat([{"role": "user", "content": prompt}]) or "生成回答失败"

    def generate_summary(self, text: str) -> str:
        """
        生成文档摘要
        """
        if not text: return "无内容"
        safe_text = text[:5000] # 截断
        prompt = f"请对以下文档内容生成一份精简摘要（200字以内），并列出关键数据点：\n\n{safe_text}"
        return self.chat([{"role": "user", "content": prompt}]) or "摘要生成失败"

    def rewrite_query(self, query: str) -> str:
        """
        查询重写
        """
        prompt = f"""请将以下搜索查询重写为一个更详细、包含更多上下文关键词的陈述句，以便于向量检索。
        
        原始查询: "{query}"
        重写后:"""
        
        res = self.chat([{"role": "user", "content": prompt}], max_tokens=200)
        return res if res else query
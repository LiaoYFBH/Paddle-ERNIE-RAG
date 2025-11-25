import os
import logging
import random
from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility
from ernie_client import ERNIEClient

# 配置日志
logger = logging.getLogger("vector_store")
logger.setLevel(logging.INFO)

class MilvusVectorStore:
    def __init__(self, uri, token, collection_name, embedding_service_url=None, qianfan_api_key=None):
        self.collection_name = collection_name
        self.uri = uri
        self.token = token
        self.embedding_client = ERNIEClient() 
        self._connect_milvus()
        self._init_collection()

    def _connect_milvus(self):
        try:
            if connections.has_connection("default"):
                logger.info(f"♻️ 检测到已有连接，复用 default 连接 (URI: {self.uri})")
                return
            
            if self.uri.endswith(".db"):
                logger.info(f"📂 连接本地 Milvus Lite: {self.uri}")
                connections.connect("default", uri=self.uri)
            else:
                logger.info(f"🌐 连接 Milvus 服务器: {self.uri}")
                connections.connect("default", uri=self.uri, token=self.token)
        except Exception as e:
            logger.error(f"❌ Milvus 连接失败: {e}")
            if not self.uri.endswith(".db") and not connections.has_connection("default"):
                connections.connect("default", uri="./demo_data.db")

    def _init_collection(self):
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="filename", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="page", dtype=DataType.INT64),
            FieldSchema(name="chunk_id", dtype=DataType.INT64),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=384)
        ]
        schema = CollectionSchema(fields, "PDF QA Collection")

        if not utility.has_collection(self.collection_name):
            self.collection = Collection(self.collection_name, schema)
            index_params = {
                "metric_type": "L2", 
                "index_type": "FLAT", 
                "params": {} 
            }
            self.collection.create_index(field_name="embedding", index_params=index_params)
            logger.info(f"✨ 创建新集合 (FLAT 索引): {self.collection_name}")
        else:
            self.collection = Collection(self.collection_name)
            logger.info(f"📚 加载已有集合: {self.collection_name}")
        
        self.collection.load()

    def get_embeddings(self, texts):
        if not texts: return []
        try:
            if hasattr(self.embedding_client, 'get_embeddings'):
                return self.embedding_client.get_embeddings(texts)
            else:
                return [self.embedding_client.get_embedding(t) for t in texts]
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return []

    def _keyword_search(self, query, top_k=50, expr=None):
        """
        关键词检索 (带简易分词/停用词过滤)
        """
        results = []
        try:
            #  关键词提取逻辑
            import re
            # 定义要剔除的：标点、疑问词、虚词、通用动词
            # (解释|是什么|含义|的|中|文章|图片|这个|篇|请问|以及|[\s\?？\.,，。!！])
            stop_patterns = r"(解释|是什么|含义|的|中|文章|图片|这个|篇|请问|以及|[\s\?？\.,，。!！])"
            
            clean_query = re.sub(stop_patterns, "", query).strip()
            
            final_query = clean_query if len(clean_query) > 0 else query
            
            # print(f"DEBUG: 原句[{query}] -> 提取关键词[{final_query}]") # 调试用

            keyword_expr = f'content like "%{final_query}%"'
            
            # 如果外部传来了 expr (比如 filename == 'xxx')，需要和关键词条件合并
            if expr:
                final_expr = f"({expr}) and ({keyword_expr})"
            else:
                final_expr = keyword_expr
            
            # 执行 Milvus 查询 ===
            res = self.collection.query(
                expr=final_expr,
                output_fields=["filename", "page", "content", "chunk_id"],
                limit=top_k
            )
            
            # 格式化结果 ===
            for hit in res:
                results.append({
                    "content": hit.get("content"),
                    "filename": hit.get("filename"),
                    "page": hit.get("page"),
                    "chunk_id": hit.get("chunk_id"),
                    "semantic_score": 0.0,  
                    "raw_score": 100.0,     
                    "type": "keyword",
                    "id": hit.get("id")
                })
        except Exception as e:
            print(f"⚠️ 关键词检索跳过: {e}")
            
        return results
    def search(self, query: str, top_k: int = 10, **kwargs):
        """
        【高精度混合检索】
        新增 **kwargs 以接收 main_local.py 传来的 expr 参数
        """
        expr = kwargs.get('expr', None)

        # === 向量检索 (Dense) ===
        dense_results = []
        try:
            query_vector = self.embedding_client.get_embedding(query)
            if query_vector:
                # FLAT 索引不需要 nprobe
                search_params = {"metric_type": "L2", "params": {}} 
                
                milvus_res = self.collection.search(
                    data=[query_vector],
                    anns_field="embedding", 
                    param=search_params,
                    limit=top_k * 5,
                    expr=expr, 
                    output_fields=["filename", "page", "content", "chunk_id"]
                )
                
                for hit in milvus_res[0]:
                    # L2距离越小越好，转换为 0-100 分数
                    raw_score = 1.0 / (1.0 + hit.distance) * 100
                    dense_results.append({
                        "content": hit.entity.get("content"),
                        "filename": hit.entity.get("filename"),
                        "page": hit.entity.get("page"),
                        "chunk_id": hit.entity.get("chunk_id"),
                        "semantic_score": hit.distance, 
                        "raw_score": raw_score,
                        "type": "dense",
                        "id": hit.id
                    })
        except Exception as e:
            print(f"❌ 向量检索异常: {e}")

        # === 关键词检索 (Keyword) ===
        keyword_results = self._keyword_search(query, top_k=top_k * 5, expr=expr)

        # === RRF 融合 ===
        rank_dict = {}
        
        def apply_rrf(results_list, weight=1.0):
            for rank, item in enumerate(results_list):
                doc_id = item.get('id')
                if not doc_id: 
                    # 如果没有ID，尝试用 chunk_id 或 内容哈希
                    doc_id = item.get('chunk_id') or hash(item.get('content'))
                
                if doc_id not in rank_dict:
                    rank_dict[doc_id] = {"data": item, "score": 0.0}
                
                # RRF 公式
                rank_dict[doc_id]["score"] += weight * (1.0 / (60 + rank))

        apply_rrf(dense_results, weight=1.0)
        apply_rrf(keyword_results, weight=3.0)

        # === 排序输出 ===
        sorted_docs = sorted(rank_dict.values(), key=lambda x: x['score'], reverse=True)
        final_results = [item['data'] for item in sorted_docs[:top_k * 2]]
        
        print(f"🔍 混合检索({query}): 向量{len(dense_results)} + 关键词{len(keyword_results)} -> 融合{len(final_results)}")
        return final_results

    
    def insert_documents(self, documents):
        if not documents: return
        print(f"⚡ 正在请求 Embedding (共 {len(documents)} 条)...")
        texts = [doc['content'] for doc in documents]
        
        # 调用 Embedding
        embeddings = self.get_embeddings(texts)

        valid_docs, valid_vectors = [], []
        failed_count = 0
        
        for i, emb in enumerate(embeddings):
            if emb and len(emb) == 384:
                valid_docs.append(documents[i])
                valid_vectors.append(emb)
            else:
                failed_count += 1
        
        if failed_count > 0:
            print(f"⚠️ 警告: 有 {failed_count} 条片段 Embedding 失败（可能是网络或Key问题）")
            
        if not valid_docs: 
            print("❌ 严重错误: 所有片段 Embedding 均失败，数据未入库！")
            print("👉 请检查: 1. AISTUDIO_ACCESS_TOKEN 是否正确/过期")
            print("👉 请检查: 2. 网络是否通畅")
            return

        try:
            data = [
                [doc['filename'] for doc in valid_docs],
                [doc['page'] for doc in valid_docs],
                [doc['chunk_id'] for doc in valid_docs],
                [doc['content'] for doc in valid_docs],
                valid_vectors
            ]
            self.collection.insert(data)
            self.collection.flush() # 强制刷盘
            logger.info(f"✅ 成功入库: 已插入 {len(valid_vectors)} 条数据")
        except Exception as e:
            print(f"❌ Milvus 写入异常: {e}")
    #
    def delete_document(self, filename):
        """
        根据文件名删除向量数据
        """
        if not filename: return "❌ 文件名为空"
        try:
            # 1. 执行删除 (使用 expr 表达式)
            # 注意：Milvus 的 delete 是逻辑删除
            self.collection.delete(expr=f'filename == "{filename}"')
            
            # 2. 强制刷盘 (让删除立即生效)
            self.collection.flush()
            
            logger.info(f"🗑️ 已从库中删除文档: {filename}")
            return f"✅ 已成功删除: {filename}"
        except Exception as e:
            err_msg = f"❌ 删除失败: {e}"
            logger.error(err_msg)
            return err_msg
    def list_documents(self):
        try:
            res = self.collection.query(expr="id > 0", output_fields=["filename"], limit=16384)
            return sorted(list(set([r['filename'] for r in res])))
        except: return []

    def get_document_content(self, filename):
        try:
            res = self.collection.query(expr=f"filename == '{filename}'", output_fields=["content", "page"], limit=1000)
            res.sort(key=lambda x: x['page'])
            return "\n\n".join([r['content'] for r in res])
        except: return ""

    def test_self_recall(self, sample_size=20):
        """
        自回归召回测试：
        从库中随机取 N 条数据，用它们自己的内容去搜，看 Top-1 是否是自己。
        证明 FLAT 索引的准确性。
        """
        try:
            total = self.collection.num_entities
            if total == 0: return "❌ 库为空，无法测试"

            limit = min(100, total)
            res = self.collection.query(expr="id > 0", output_fields=["id", "content"], limit=limit)
            
            if not res: return "❌ 无法获取数据"
            
            samples = random.sample(res, min(sample_size, len(res)))
            
            hits = 0
            for item in samples:
                doc_id = item['id']
                content = item['content']
                emb = self.embedding_client.get_embedding(content)
                if not emb: continue
                
                search_res = self.collection.search(
                    data=[emb], 
                    anns_field="embedding", 
                    param={"metric_type": "L2", "params": {}}, # FLAT无参
                    limit=1,
                    output_fields=["id"]
                )
                
                # 检查 Top-1 ID 是否匹配
                if search_res and len(search_res[0]) > 0:
                    top1_id = search_res[0][0].id
                    if top1_id == doc_id:
                        hits += 1
            
            recall_rate = (hits / len(samples)) * 100
            return f"✅ 召回测试 ({len(samples)}条样本): 准确率 {recall_rate:.1f}%"
            
        except Exception as e:
            return f"❌ 测试出错: {e}"
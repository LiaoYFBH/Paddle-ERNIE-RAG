import logging
from typing import List, Dict, Any, Tuple
from fuzzywuzzy import fuzz
import re

logger = logging.getLogger("pdf_qa")

class RerankerAndFilterV2:
    """
    Reranker V2
    """
    def __init__(self):
        self.use_paddlenlp = False

    def _extract_keywords(self, text: str) -> set:
        """提取文本关键词（去除停用词）"""
        stop_words = {
            '的', '了', '是', '在', '和', '与', '或', '等', '中', '上', '下', 
            '为', '有', '以', '及', '将', '对', '从', '到', '由', '被', '把',
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'
        }
        
        words = set()
        for char in text:
            if '\u4e00' <= char <= '\u9fff' and char not in stop_words:
                words.add(char)
        
        english_words = re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())
        words.update([w for w in english_words if w not in stop_words])
        
        return words

    def _calculate_composite_score(self, query: str, chunk: Dict[str, Any]) -> float:
        """
        综合打分算法 (Robust Version)
        """
        content = chunk.get('content', '')
        
        fuzzy_score = fuzz.partial_ratio(query, content)
        
        query_keywords = self._extract_keywords(query)
        content_keywords = self._extract_keywords(content)
        
        if query_keywords:
            keyword_hits = len(query_keywords & content_keywords)
            keyword_coverage = (keyword_hits / len(query_keywords)) * 100
        else:
            keyword_coverage = 0
        
        # Milvus 语义相似度
        milvus_distance = chunk.get('semantic_score')
        
        if milvus_distance is None:
            milvus_similarity = 80.0 
        else:
            milvus_similarity = 100 / (1 + milvus_distance * 0.1)
        
        # 位置权重
        position_bonus = 0
        if 'milvus_rank' in chunk:
            rank = chunk['milvus_rank']
            position_bonus = max(0, 20 - rank)
        
        # 长度惩罚
        content_len = len(content)
        if 200 <= content_len <= 600:
            length_score = 100
        elif content_len < 200:
            length_score = 50 + (content_len / 200) * 50
        else:
            length_score = 100 - min(50, (content_len - 600) / 20)
        
        # 专有名词加分
        # 1. 英文正则保持不变
        en_pattern = r'\b[A-Z][a-z]+\b|[A-Z]{2,}'
        
        # 2. 简单的中文关键词提取（这里用双字以上匹配作为简易替代）
        # 如果 query 只有中文，把所有长度>=2的词都视为潜在“关键实体”进行匹配
        def extract_potential_nouns(text):
            res = set(re.findall(en_pattern, text))
            # 提取中文连续字符 (简单粗暴，仅供优化参考)
            zh_words = [w for w in re.split(r'[^\u4e00-\u9fa5]', text) if len(w) >= 2]
            res.update(zh_words)
            return res

        query_proper_nouns = extract_potential_nouns(query)
        content_proper_nouns = extract_potential_nouns(content)        
        proper_noun_bonus = 0
        if query_proper_nouns:
            hits = len(query_proper_nouns & content_proper_nouns)
            if hits > 0:
                proper_noun_bonus = 30
        
        base_score = (
            fuzzy_score * 0.25 +
            keyword_coverage * 0.25 +
            milvus_similarity * 0.35 +
            length_score * 0.15
        )
        
        final_score = base_score + position_bonus + proper_noun_bonus

        chunk['score_details'] = {
            'final': final_score,
            'fuzzy': fuzzy_score,
            'kw': keyword_coverage,
            'vec': milvus_similarity
        }
        
        return final_score

    def process(self, query: str, chunks: List[Dict[str, Any]], fuzzy_threshold: int = 10) -> Tuple[List[Dict[str, Any]], str]:
        if not chunks:
            return [], "no_chunks"
        
        for rank, chunk in enumerate(chunks, 1):
            chunk['milvus_rank'] = rank
        
        for chunk in chunks:
            score = self._calculate_composite_score(query, chunk)
            chunk['composite_score'] = score
        
        sorted_chunks = sorted(chunks, key=lambda c: c.get('composite_score', 0), reverse=True)
        
        return sorted_chunks, "success"
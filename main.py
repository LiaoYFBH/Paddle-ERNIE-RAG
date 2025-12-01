import os
import socket
import gradio as gr
import backend  # 引入逻辑层

# ==============================================================================
# UI 样式 
# ==============================================================================
modern_css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

body, .gradio-container {
    font-family: 'Inter', -apple-system, sans-serif !important;
    background-color: #f9fafb !important;
    --primary-color: #6366f1;
}

/* === 1. 布局容器 === */
.main-content {
    max-width: 1400px !important;
    margin: 0 auto !important;
    height: 100% !important;
    position: relative !important; /* 关键：为右上角按钮提供定位锚点 */
}

/* === 2. 侧边栏静态提示 (修正版：强制固定在浏览器右上角) === */
.sidebar-hint {
    position: fixed !important;    /* 改为 fixed，无视任何容器 */
    top: 22px !important;          /* 垂直高度与 Tab 栏文字对齐 */
    right: 35px !important;        /* 给最右侧的原生箭头留出位置 */
    z-index: 99999 !important;     /* 确保在最上层 */
    
    font-size: 13px !important;
    font-weight: 600 !important;
    color: #9ca3af !important;     /* 浅灰色 */
    background: transparent !important;
    
    display: flex !important;
    align-items: center !important;
    gap: 4px !important;
    pointer-events: none !important; /* 关键：鼠标穿透，防止挡住后面的点击 */
    user-select: none !important;
}

/* === 3. 聊天区域 === */
.chat-container {
    background: transparent !important;
    border: none !important;
}

/* === 4. 底部输入区布局 === */
.input-row {
    display: flex !important;
    align-items: center !important; /* 改为垂直居中，修复高度微小差异导致的错位 */
    justify-content: space-between !important;
    gap: 8px !important; /* 稍微减小间距，更紧凑 */
    padding-bottom: 20px !important;
    
    width: 100% !important;
    max-width: 100% !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
}

/* === 5. 输入框美化  === */
.custom-textbox {
    flex-grow: 1 !important;
    flex-shrink: 1 !important;
    min-width: 0 !important; /* 防止溢出 */
    width: auto !important;
}

.custom-textbox textarea {
    background-color: #ffffff !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 12px !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.05) !important;
    padding: 10px 14px !important; /* 微调内边距 */
    font-size: 15px !important;
    color: #1f2937 !important;
    
    /* 🔥 高度控制：确保与左右按钮(48px)视觉一致 🔥 */
    min-height: 48px !important;
    height: 48px !important; /* 初始高度固定，避免忽高忽低 */
    max-height: 120px !important;
    
    line-height: 1.5 !important;
    resize: none !important;
}

/* 隐藏 Gradio 默认容器的多余边距 */
.custom-textbox .block, 
.custom-textbox .wrapper, 
.custom-textbox .container, 
.custom-textbox fieldset {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    margin: 0 !important;
    box-shadow: none !important;
}

/* === 6. 按钮样式 (正方形图标) === */
.action-btn {
    height: 48px !important; /* 与输入框最小高度一致 */
    width: 48px !important;
    max-width: 48px !important;
    min-width: 48px !important; /* 锁死宽度，防止被拉伸 */
    border-radius: 12px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 0 !important;
    font-size: 20px !important;
    margin-bottom: 2px !important; /* 微调以实现完美底部对齐 */
    cursor: pointer !important;
    transition: all 0.2s !important;
}
.action-btn:active { transform: scale(0.95); }

/* 发送按钮 - 紫色渐变 */
.send-btn {
    background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%) !important;
    color: white !important;
    border: none !important;
    box-shadow: 0 4px 10px rgba(99, 102, 241, 0.3) !important;
}
.send-btn:hover { opacity: 0.9; transform: scale(1.05); }

/* 清空按钮 - 白色 */
.trash-btn {
    background: #ffffff !important;
    color: #9ca3af !important;
    border: 1px solid #e5e7eb !important;
}
.trash-btn:hover {
    color: #ef4444 !important;
    border-color: #fca5a5 !important;
    background: #fef2f2 !important;
}

/* === 7. 左侧极简列表栏 === */
.clean-sidebar {
    background: transparent !important;
    border-right: 1px solid #e5e7eb;
    padding-right: 25px !important;
    display: flex;
    flex-direction: column;
    gap: 15px;
}
.app-logo {
    font-size: 22px;
    font-weight: 800;
    background: linear-gradient(135deg, #4f46e5 0%, #9333ea 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 20px;
    line-height: 1.3;
}
.sidebar-label {
    font-size: 11px;
    font-weight: 700;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: -5px;
}

/* === 8. 卡片与其他组件 === */
.modern-card {
    background: #ffffff !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 16px !important;
    padding: 24px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
    margin-bottom: 20px;
}
.danger-zone {
    border: 1px solid #fee2e2 !important;
    background: #fffcfc !important;
    border-radius: 12px;
    padding: 20px;
}
.tabs { margin-top: 5px !important; background: transparent !important; border-bottom: 1px solid #e5e7eb !important; }
.tab-nav { border: none !important; }
.tab-nav button { font-weight: 500 !important; font-size: 14px !important; }
.tab-nav button.selected { color: #6366f1 !important; border-bottom: 2px solid #6366f1 !important; font-weight: 600 !important; }
.floating-bar {
    background: #ffffff;
    border-top: 1px solid #e5e7eb;
    padding: 15px 20px;
    border-radius: 0 0 16px 16px;
    display: flex; align-items: center; gap: 15px;
}
.no-padding { padding: 0 !important; }
.row-center { display: flex !important; align-items: center !important; }
.card-header { font-size: 16px; font-weight: 700; color: #1f2937; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }

footer { display: none !important; }

/* === 9. 侧边栏专属优化 (Markdown 渲染) === */
.gradio-container .prose p, 
.gradio-container .prose li {
    font-size: 15px !important;
    line-height: 1.6 !important;
}
.gradio-container .prose h1 { font-size: 20px !important; margin-bottom: 15px !important; }
.gradio-container .prose h2 { font-size: 18px !important; margin-top: 20px !important; }
.gradio-container .prose h3 { font-size: 16px !important; color: #4f46e5 !important; }
.gradio-container .prose code {
    font-size: 13px !important;
    color: #c026d3 !important;
    background: #fdf4ff !important;
}

/* === 10. 图片预览胶囊样式 === */
.img-preview-mini {
    display: flex !important;
    align-items: center !important;
    background: #ffffff !important;
    border: 1px solid #e5e7eb !important;
    border-left: 4px solid #6366f1 !important;
    border-radius: 12px !important;
    padding: 0 8px 0 0 !important;
    margin-right: 8px !important;
    height: 48px !important; /* 与输入框高度匹配 */
    box-shadow: 0 2px 5px rgba(0,0,0,0.05) !important;
    min-width: fit-content !important; 
    flex-shrink: 0 !important;
    overflow: visible !important;
}
.mini-img-container {
    height: 36px !important;
    width: 36px !important;
    border-radius: 6px !important;
    overflow: hidden !important;
    border: 1px solid #f3f4f6 !important;
    flex-shrink: 0 !important;
    margin: 0 10px 0 6px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
.mini-text-col {
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    white-space: nowrap !important;
    overflow: visible !important;
}
.mini-tag-text {
    font-size: 13px !important;
    font-weight: 700 !important;
    color: #4f46e5 !important;
    line-height: 1.2 !important;
}
.mini-tag-sub {
    font-size: 10px !important;
    color: #9ca3af !important;
    font-weight: 400 !important;
    line-height: 1.1 !important;
}
"""
latex_config = [
    {"left": "$$", "right": "$$", "display": True},   # 行间公式
    {"left": "$", "right": "$", "display": False},    # 行内公式
    {"left": "\\(", "right": "\\)", "display": False}, # 标准 LaTeX 行内
    {"left": "\\[", "right": "\\]", "display": True}   # 标准 LaTeX 行间
]
# ==============================================================================
# 主题配置
# ==============================================================================
theme = gr.themes.Soft(
    primary_hue="indigo",
    secondary_hue="slate",
    radius_size="md",
    font=[gr.themes.GoogleFont("Inter"), "sans-serif"]
).set(
    body_background_fill="#f9fafb",
    block_background_fill="#ffffff",
    block_border_width="0px",
    input_background_fill="#ffffff",
)

# === 工具函数 ===
def load_tutorial_content():
    file_path = "tutorial/tutorial.md"
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"### ❌ 读取教程失败\n{str(e)}"
    else:
        return "### ⚠️ 未找到教程文件\n请在项目根目录创建 `tutorial.md` 文件。"
def create_normal_input(label, value, placeholder="", info=""):
    """
    创建一个与 create_masked_input 结构完全一致的普通输入框，确保左右对齐
    """
    with gr.Group():
        if label:
            # 使用与 create_masked_input 完全相同的 HTML 标签样式
            gr.HTML(f'<div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:6px;">{label}</div>')
        # container=False 去除 Gradio 自带的外框，防止双重边距
        return gr.Textbox(show_label=False, value=value, placeholder=placeholder, info=info, interactive=True, container=False, scale=10)
def create_masked_input(label, value, placeholder="", link_info=""):
    with gr.Group():
        if label:
            link_html = f'<a href="{link_info[1]}" target="_blank" style="float:right;font-size:12px;color:#6366f1;text-decoration:none;">获取 Key &rarr;</a>' if link_info else ""
            gr.HTML(f'<div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:6px;">{label} {link_html}</div>')
        with gr.Row(variant="compact", elem_classes="pwd-group"):
            txt = gr.Textbox(show_label=False, value=value, placeholder=placeholder, type="password", interactive=True, container=False, scale=10)
            btn_eye = gr.Button("👁️", scale=1, min_width=30, elem_classes="secondary-btn")

    def toggle_visibility(current_val, current_type):
        return (gr.update(type="text"), "text") if current_type == "password" else (gr.update(type="password"), "password")
    type_state = gr.State("password")
    btn_eye.click(fn=toggle_visibility, inputs=[txt, type_state], outputs=[txt, type_state])
    return txt

# ==============================================================================
# 界面构建
# ==============================================================================
with gr.Blocks(title="多文档高精度智能分析与问答系统", theme=theme, css=modern_css) as demo:
    
    image_context_state = gr.State(None)
    with gr.Tabs():
        
        # ============================================================
        # Tab 1: 💬 智能问答
        # ============================================================
        with gr.Tab("💬 智能问答"):
            
            with gr.Column(elem_classes="main-content"):
                gr.HTML("""
                    <div class="sidebar-hint">
                        查看使用教程 →
                    </div>
                """)
                
                with gr.Row():
                    
                    # --- 左侧：品牌 & 极简列表 ---
                    with gr.Column(scale=1, min_width=280, elem_classes="clean-sidebar"):
                        
                        gr.HTML("""
                        <div class="app-logo">
                            ⚡ 高精度多文档<br>智能分析与问答系统
                        </div>
                        """)
                        
                        gr.HTML('<div class="sidebar-label">Knowledge Base</div>')
                        qa_col_select = gr.Dropdown(show_label=False, choices=[], value=None, allow_custom_value=True, container=True, interactive=True)
                        
                        gr.HTML('<div class="sidebar-label">Document Filter</div>')
                        qa_file_select = gr.Dropdown(show_label=False, choices=["全部文档 (Global QA)"], value="全部文档 (Global QA)", allow_custom_value=True, interactive=True)
                        
                        gr.HTML('<div style="height:10px"></div>')
                        refresh_btn = gr.Button("🔄 刷新列表", size="sm", variant="secondary")

                    # --- 右侧：沉浸式对话区 ---
                    with gr.Column(scale=5):
                        # 降低高度，确保输入框在可视区域
                        chatbot = gr.Chatbot(
                            label="Conversation",
                            height=450,  
                            show_label=False, 
                            type='messages',
                            avatar_images=(None, "https://cdn-icons-png.flaticon.com/512/6134/6134346.png"),
                            elem_classes="chat-container",
                            placeholder="# 👋 Document AI\n\nAsk anything about your documents.",
                            latex_delimiters=latex_config
                        )
                        with gr.Row(elem_classes="input-row", equal_height=False):
                            # === 1. 左侧：迷你预览胶囊 (默认隐藏，scale=0 不占地) ===
                            with gr.Group(visible=False, elem_classes="img-preview-mini") as img_preview_group:
                                with gr.Row(elem_classes="row-center no-padding"):
                                    # 图片缩略图
                                    with gr.Column(elem_classes="mini-img-container", min_width=42, scale=0):
                                        preview_img = gr.Image(
                                            show_label=False, 
                                            container=False, 
                                            interactive=False, 
                                            show_download_button=False, 
                                            show_fullscreen_button=False,
                                            height=42, 
                                            width=42
                                        )
                                    
                                    # 文字提示
                                    with gr.Column(min_width=100, scale=0):
                                        gr.HTML("""
                                        <div style="display:flex;flex-direction:column;">
                                            <span class="mini-tag-text">📷 图表预览</span>
                                            <span class="mini-tag-sub">Context Locked</span>
                                        </div>
                                        """)
                                    
                                    # 关闭按钮
                                    btn_clear_img = gr.Button("✕", elem_classes="mini-close-btn", size="sm", scale=0, min_width=24)

                            # === 2. 中间：输入框 (scale=10 自动填满剩余空间) ===
                            msg = gr.Textbox(
                                show_label=False, 
                                placeholder="请输入您的问题...", 
                                container=True, 
                                max_lines=8,
                                lines=1,
                                autofocus=True,
                                elem_classes="custom-textbox", 
                                scale=10  # 关键：占据剩余宽度
                            )
                            
                            # === 3. 右侧：功能按钮 ===
                            clear_btn = gr.Button("🗑️", elem_classes="action-btn trash-btn", size="sm", scale=0, min_width=42)
                            submit_btn = gr.Button("➤", elem_classes="action-btn send-btn", size="sm", scale=0, min_width=42)
                        
                        gr.HTML("""
                                <div style="margin-top: 6px; font-size: 13px; color: #6366f1; background-color: #eef2ff; padding: 8px 12px; border-radius: 8px; border: 1px solid #e0e7ff;">
                                    💡 <b>操作提示：</b> 点击展开下方“分析详情”，可选中图表进行提问</b>。
                                </div>
                                """)
                        # 分析详情
                        with gr.Accordion("📊 分析详情", open=False):
                             with gr.Column(elem_classes="modern-card"):
                                with gr.Row():
                                    with gr.Column():
                                        gr.Markdown("#### 💡 置信度")
                                        qa_metric = gr.Textbox(value="N/A", show_label=False, interactive=False)
                                    with gr.Column():
                                        gr.Markdown("#### 📄 智能摘要")
                                        doc_summary = gr.Markdown(value="*暂无摘要*", latex_delimiters=latex_config)
                                gr.HTML('<hr style="margin: 15px 0; border-top: 1px dashed #e5e7eb;">')
                                gr.Markdown("#### 🖼️ 提取图表")
                                doc_gallery = gr.Gallery(show_label=False, height=180, object_fit="contain", columns=4,interactive=True)
                                
        # ============================================================
        # Tab 2 & 3: 管理与配置 (Perfect & Unchanged)
        # ============================================================
        
        # ... 知识库管理 ...
        with gr.Tab("📂 知识库管理"):
             
             gr.HTML('<div style="height: 20px;"></div>')
             with gr.Row():
                with gr.Column(scale=1, elem_classes="modern-card"):
                    gr.HTML('<div class="card-header"><span>📤</span> 文档解析与入库</div>')
                    upload_col_select = gr.Dropdown(label="目标知识库", choices=[], allow_custom_value=True, info="选择或新建")
                    gr.HTML('<div style="height:10px"></div>')
                    files_input = gr.File(label="PDF 文件", file_count="multiple", type="filepath", height=120)
                    
                    gr.HTML('<div style="height:15px"></div>')
                    with gr.Row():
                        # 上传按钮
                        upload_btn = gr.Button("🚀 上传并解析", variant="primary", scale=3)
                        # 终止按钮
                        stop_btn = gr.Button("🛑 终止任务", variant="stop", scale=1)
                    gr.HTML('<div style="height:20px"></div>')
                    # upload_log = gr.Textbox(show_label=False, lines=15, max_lines=25, placeholder="等待任务...", text_align="left", elem_classes="code-box")
                # 日志框：设为 interactive=False 防止用户输入，但允许滚动查看
                    upload_log = gr.Textbox(
                        show_label=True, 
                        label="实时执行日志",
                        lines=12, 
                        max_lines=20, 
                        placeholder="点击上传后，此处显示实时进度...", 
                        elem_classes="code-box",
                        interactive=False,
                        autoscroll=True  # 自动滚动到底部
                    )
                with gr.Column(scale=1):
                    with gr.Column(elem_classes="modern-card"):
                        gr.HTML('<div class="card-header"><span>✨</span> 快速创建</div>')
                        with gr.Row():
                            new_col_name = gr.Textbox(show_label=False, placeholder="输入新库名称", scale=3, container=False)
                            create_btn = gr.Button("创建", scale=1)
                        create_msg = gr.Label(show_label=False, visible=False)

                    with gr.Column(elem_classes="modern-card danger-zone"):
                        gr.HTML('<div style="color:#b91c1c; font-weight:700; margin-bottom:10px;">⚠️ 危险操作区</div>')
                        with gr.Row(variant="compact", elem_classes="row-center"):
                            del_col_select = gr.Dropdown(show_label=False, choices=[], info="选择要删除的库", scale=3, container=False)
                            del_btn = gr.Button("删除库", variant="stop", scale=1)
                        del_col_msg = gr.Textbox(show_label=False, visible=False)
                        gr.HTML('<div style="height:10px"></div>')
                        with gr.Row(variant="compact", elem_classes="row-center"):
                            del_file_select = gr.Dropdown(show_label=False, choices=[], allow_custom_value=True, info="删除文件", scale=3, container=False)
                            btn_del_file = gr.Button("删除文件", variant="stop", scale=1)
                        del_file_msg = gr.Textbox(show_label=False, visible=False)

                    with gr.Column(elem_classes="modern-card"):
                        gr.HTML('<div class="card-header"><span>🧪</span> 效果诊断</div>')
                        with gr.Row():
                            test_recall_btn = gr.Button("🔍 运行召回率测试", size="sm")
                        gr.HTML('<div style="height:10px"></div>')
                        test_result_box = gr.Textbox(show_label=False, lines=2, placeholder="测试结果...", container=False)

        # ... 系统配置 ...
        with gr.Tab("⚙️ 系统配置"):
            gr.HTML('<div style="height: 20px;"></div>')
            with gr.Row():
                # === 1. LLM 配置 ===
                with gr.Column(elem_classes="modern-card"):
                    gr.HTML('<div class="card-header"><span>🧠</span> 大模型 (LLM)</div>')
                    
                    llm_api_base = gr.Textbox(
                        label="Base URL", 
                        value=os.getenv("LLM_API_BASE", "https://aistudio.baidu.com/llm/lmapi/v3"),
                        info="千帆/AIStudio URL"
                    )
                    llm_model = gr.Textbox(label="Model Name", value=os.getenv("LLM_MODEL", "ernie-4.5-turbo-vl"))
                    
                    # 带链接的 Key
                    llm_api_key = create_masked_input(
                        "API Key", 
                        os.getenv("LLM_API_KEY", os.getenv("AISTUDIO_ACCESS_TOKEN", ""))
                        # link_info=("获取 Key", "https://aistudio.baidu.com/account/accessToken")
                    )

                # === 2. Embedding 配置 ===
                with gr.Column(elem_classes="modern-card"):
                    gr.HTML('<div class="card-header"><span>🔢</span> 向量模型 (Embedding)</div>')
                    
                    embed_api_base = gr.Textbox(
                        label="Base URL", 
                        value=os.getenv("EMBED_API_BASE", "https://aistudio.baidu.com/llm/lmapi/v3"),
                        info="千帆/AIStudio URL"
                    )
                    embed_model = gr.Textbox(label="Model Name", value=os.getenv("EMBED_MODEL", "embedding-v1"))
                    
                    # 带链接的 Key
                    embed_api_key = create_masked_input(
                        "API Key", 
                        os.getenv("EMBED_API_KEY", os.getenv("AISTUDIO_ACCESS_TOKEN", ""))#, 
                        # link_info=("获取 Key", "https://aistudio.baidu.com/account/accessToken")
                    )

            # === 3. OCR & Milvus 配置 ===
            with gr.Column(elem_classes="modern-card"):
                gr.HTML('<div class="card-header"><span>🛠️</span> 基础配置</div>')
                with gr.Row():
                    with gr.Column(scale=1):
                         ocr_url = create_normal_input(
                             label="OCR API URL", 
                             value=os.getenv("OCR_API_URL", ""), 
                             info="获取方式见教程"
                         )
                    with gr.Column(scale=1):
                         ocr_token = create_masked_input(
                             "OCR Token", 
                             os.getenv("OCR_ACCESS_TOKEN", os.getenv("AISTUDIO_ACCESS_TOKEN", "")),
                             link_info=("获取 Token", "https://aistudio.baidu.com/account/accessToken")
                         )
                         
                gr.HTML('<hr style="margin: 20px 0; border-top: 1px dashed #e5e7eb;">')
                
                # use_local_mode = gr.Checkbox(label="📂 使用本地 Milvus Lite (无需服务器)", value=False)
                with gr.Row():
                    with gr.Column(scale=1):
                        tk_uri = create_normal_input(label="Milvus URI", value=os.getenv("MILVUS_URI", ""), info="Zilliz Cloud")
                    with gr.Column(scale=1):
                        tk_token = create_masked_input(
                            "Milvus Token", 
                            os.getenv("MILVUS_TOKEN", ""),
                            link_info=("获取 Token(详见教程)", "https://cloud.zilliz.com/")
                        )

            # === 4. 底部保存栏 ===
            with gr.Column(elem_classes="modern-card no-padding"):
                 with gr.Row(elem_classes="floating-bar"):
                    with gr.Column(scale=4):
                        api_qps = gr.Slider(0.5, 10.0, value=1.0, step=0.5, label="API 速率限制 (QPS)")
                    with gr.Column(scale=2):
                        connect_log = gr.Textbox(show_label=False, lines=1, placeholder="未连接", container=False, text_align="right")
                    with gr.Column(scale=1, min_width=120):
                        btn_connect = gr.Button("💾 保存并连接", variant="primary", size="lg")
    # ==============================================================================
    with gr.Sidebar(label="📖 使用教程", open=False, position="right"):
        gr.Markdown(value=load_tutorial_content())
    # ==============================================================================
    # 逻辑绑定
    # ==============================================================================
    # 1. Gallery 点击事件 -> 获取路径 -> 更新 State -> 显示预览区
    def on_img_select(evt: gr.SelectData, col, file):
        data, toast = backend.on_gallery_select(evt, col, file)
        
        if data:
            gr.Info(toast) # 弹出提示
            
            return data, gr.update(visible=True), data['path']
        return None, gr.update(visible=False), None
    doc_gallery.select(
        on_img_select, 
        inputs=[qa_col_select, qa_file_select], 
        outputs=[image_context_state, img_preview_group, preview_img]
    )

    # 2. 取消选中图片
    def clear_img_context():
        # 四个返回值：gr.update(selected_index=None) 用于清除相册选中态
        return None, gr.update(visible=False), None, gr.update(selected_index=None)
    btn_clear_img.click(
        clear_img_context, 
        outputs=[image_context_state, img_preview_group, preview_img, doc_gallery] # 👈 记得加上 doc_gallery
    )
    # 3. 发送消息 (更新 Inputs 列表，加入 image_context_state)
    # 第一处：回车发送
    msg.submit(
        backend.chat_respond, 
        inputs=[msg, chatbot, qa_col_select, qa_file_select, image_context_state], 
        outputs=[chatbot, msg, qa_metric, image_context_state] # ✅ 只有4个
    ).then(
        lambda: (gr.update(visible=False), None, gr.update(selected_index=None)), 
        outputs=[img_preview_group, preview_img, doc_gallery]
    )

    # 第二处：按钮发送
    submit_btn.click(
        backend.chat_respond, 
        inputs=[msg, chatbot, qa_col_select, qa_file_select, image_context_state], 
        outputs=[chatbot, msg, qa_metric, image_context_state] # ✅ 只有4个
    ).then(
        lambda: (gr.update(visible=False), None, gr.update(selected_index=None)), 
        outputs=[img_preview_group, preview_img, doc_gallery]
    )
    # use_local_mode.change(lambda x: (gr.update(value="./data.db"), gr.update(value="")) if x else (gr.update(value=os.getenv("MILVUS_URI")), gr.update(value=os.getenv("MILVUS_TOKEN"))), inputs=[use_local_mode], outputs=[tk_uri, tk_token])
    btn_connect.click(backend.initialize_system, inputs=[llm_api_base, llm_api_key, llm_model, embed_api_base, embed_api_key, embed_model, ocr_url, ocr_token, tk_uri, tk_token, api_qps], outputs=[connect_log, qa_col_select, upload_col_select, del_col_select])
    refresh_btn.click(backend.update_file_list, inputs=[qa_col_select], outputs=[qa_file_select])
    qa_col_select.change(backend.update_file_list, inputs=[qa_col_select], outputs=[qa_file_select])
    upload_event = upload_btn.click(
        backend.process_uploaded_pdf, 
        inputs=[files_input, upload_col_select], 
        outputs=[upload_log] # 输出目标是日志框
    )
    
    stop_btn.click(
        fn=None, 
        inputs=None, 
        outputs=None, 
        cancels=[upload_event]
    )
    
    # 3. 链式回调：任务完成（或被终止）后，依然刷新下拉列表
    upload_event.then(backend.refresh_all_dropdowns, outputs=[qa_col_select, upload_col_select, del_col_select]) \
                .then(backend.update_file_list, inputs=[qa_col_select], outputs=[qa_file_select]) \
                .then(backend.update_file_list_for_delete, inputs=[upload_col_select], outputs=[del_file_select])
    create_btn.click(backend.create_collection_ui, inputs=[new_col_name], outputs=[upload_col_select, create_msg]).then(backend.refresh_all_dropdowns, outputs=[qa_col_select, upload_col_select, del_col_select])
    del_btn.click(backend.delete_collection_ui, inputs=[del_col_select], outputs=[upload_col_select, del_col_msg]).then(backend.refresh_all_dropdowns, outputs=[qa_col_select, upload_col_select, del_col_select])
    upload_col_select.change(backend.update_file_list_for_delete, inputs=[upload_col_select], outputs=[del_file_select])
    btn_del_file.click(backend.delete_single_file, inputs=[upload_col_select, del_file_select], outputs=[del_file_msg]).then(backend.update_file_list_for_delete, inputs=[upload_col_select], outputs=[del_file_select])
    qa_file_select.change(backend.analyze_doc_and_images, inputs=[qa_col_select, qa_file_select], outputs=[doc_summary, doc_gallery])
    # msg.submit(backend.chat_respond, inputs=[msg, chatbot, qa_col_select, qa_file_select, image_context_state], outputs=[chatbot, chatbot, msg, qa_metric, image_context_state])
    # submit_btn.click(backend.chat_respond, inputs=[msg, chatbot, qa_col_select, qa_file_select, image_context_state], outputs=[chatbot, chatbot, msg, qa_metric, image_context_state])
    clear_btn.click(lambda: ([], "", "N/A", ""), outputs=[chatbot, msg, qa_metric, image_context_state])
    test_recall_btn.click(backend.run_recall_test, inputs=[upload_col_select], outputs=[test_result_box])
    
def find_free_port(start=7860):
    for port in range(start, start+10):
        try:
            s = socket.socket()
            s.bind(('', port))
            s.close()
            return port
        except OSError: continue
    return start

abs_asset_path = os.path.abspath("assets")
if __name__ == "__main__":
    port = find_free_port()
    print(f"🚀 UI 已启动: http://127.0.0.1:{port}")
    demo.launch(server_name="127.0.0.1", server_port=port, inbrowser=True,allowed_paths=[abs_asset_path])
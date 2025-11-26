import os
import socket
import gradio as gr
import backend  # 引入逻辑层

# === 样式定义 ===
custom_css = """
:root, body, .gradio-container {
    --body-background-fill: #ffffff !important;
    --background-fill-primary: #ffffff !important;
    --background-fill-secondary: #ffffff !important;
    --block-background-fill: #ffffff !important;
    --panel-background-fill: #ffffff !important;
    background-color: #ffffff !important;
}
.gr-group, .gr-box, .gr-panel, .gr-row, .gr-column, .gr-block {
    background-color: #ffffff !important;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}
textarea, select, .gr-input, .gr-form, .wrap, input:not([type="checkbox"]):not([type="radio"]) {
    background-color: #ffffff !important;
}
.header-banner {
    background: linear-gradient(135deg, #2563eb, #3b82f6);
    color: white;
    padding: 1.5rem;
    border-radius: 12px;
    margin-bottom: 10px;
}
.header-title { font-size: 1.5rem; font-weight: 700; }
.flow-guide {
    background-color: #f0f9ff;
    border: 1px solid #bae6fd;
    color: #0369a1;
    padding: 10px;
    border-radius: 8px;
    margin-bottom: 20px;
    font-size: 0.95rem;
    text-align: center;
    font-weight: 600;
}
.chatbot-container { min-height: 600px !important; }
"""
theme = gr.themes.Soft(primary_hue="blue", secondary_hue="slate")

# === 界面构建 ===
with gr.Blocks(title="多文档智能分析与问答系统", theme=theme, css=custom_css) as demo:
    # 顶部 Banner
    gr.HTML("""
        <div class="header-banner">
            <div class="header-title">🚀 多文档智能分析与问答系统 (Pro)</div>
            <div class="header-subtitle"> Cloud OCR  · ERNIE 4.5 · Milvus</div>
        </div>
    """)
    
    # 🌟 顶部流程指引
    gr.HTML("""
        <div class="flow-guide">
            📝 使用顺序： Step 1. 系统配置 (连接) &nbsp; ➔ &nbsp; Step 2. 知识库管理 (上传/解析) &nbsp; ➔ &nbsp; Step 3. 智能问答
        </div>
    """)
    
    image_context_state = gr.State("")

    with gr.Tabs():
        # === 标签页 1: 智能问答 ===
        with gr.TabItem("💡 智能问答"):
            with gr.Group():
                with gr.Row():
                    qa_col_select = gr.Dropdown(
                        label="1. 知识库", 
                        choices=[], 
                        scale=3, 
                        allow_custom_value=True
                    )
                    qa_file_select = gr.Dropdown(
                        label="2. 文档", 
                        choices=["全部文档 (Global QA)"], 
                        value="全部文档 (Global QA)", 
                        scale=4, 
                        allow_custom_value=True
                    )
                    refresh_btn = gr.Button("🔄 刷新", scale=1)
                
                with gr.Row():
                    with gr.Column(scale=6):
                        chatbot = gr.Chatbot(label="对话", height=650, show_label=False, elem_classes="chatbot-container", type='messages')
                        with gr.Row():
                            msg = gr.Textbox(show_label=False, placeholder="输入问题...", scale=10, autofocus=True)
                            submit_btn = gr.Button("发送", variant="primary", scale=1)
                        with gr.Row():
                            qa_metric = gr.Label(label="置信度", value="N/A", scale=1)
                            clear_btn = gr.ClearButton([msg, chatbot, image_context_state], value="🧹", size="sm", scale=1)

                    with gr.Column(scale=4):
                        doc_summary = gr.Markdown(value="👈 请选择文档...", elem_classes="gr-box")
                        doc_gallery = gr.Gallery(label="OCR 提取图表", show_label=False, height=400, object_fit="contain")

            # 绑定逻辑
            refresh_btn.click(backend.update_file_list, inputs=[qa_col_select], outputs=[qa_file_select])
            qa_col_select.change(backend.update_file_list, inputs=[qa_col_select], outputs=[qa_file_select])
            qa_file_select.change(backend.analyze_doc_and_images, inputs=[qa_col_select, qa_file_select], outputs=[doc_summary, doc_gallery])
            
            chat_inputs = [msg, chatbot, qa_col_select, qa_file_select, image_context_state]
            chat_outputs = [chatbot, chatbot, msg, qa_metric, image_context_state]
            
            msg.submit(backend.chat_respond, inputs=chat_inputs, outputs=chat_outputs)
            submit_btn.click(backend.chat_respond, inputs=chat_inputs, outputs=chat_outputs)

        # === 标签页 2: 知识库管理 ===
        with gr.TabItem("🛠️ 知识库管理"):
            with gr.Row():
                with gr.Column(scale=1):
                    # 上传模块
                    with gr.Group():
                        gr.Markdown("### 📤 上传文档")
                        upload_col_select = gr.Dropdown(label="目标 Collection", allow_custom_value=True, choices=[])
                        
                        # 自定义 OCR 参数
                        custom_ocr_token = gr.Textbox(
                            label="云端 OCR API Token (可选)", 
                            placeholder="若不填，自动使用 .env 文件中配置的 AISTUDIO_ACCESS_TOKEN",
                            info="[点击获取 Access Token](https://aistudio.baidu.com/account/accessToken)"
                        )
                        custom_ocr_url = gr.Textbox(
                            label="云端 OCR API URL (可选)", 
                            placeholder="若不填，自动使用 .env 文件中配置的 OCR_API_URL",
                            info="[API说明](https://aistudio.baidu.com/paddleocr/task"
                        )

                        files_input = gr.File(label="PDF文件", file_count="multiple", type="filepath")
                        upload_btn = gr.Button("🚀 开始智能解析", variant="primary")
                        upload_log = gr.Textbox(label="日志", lines=4)
                    
                    # 测试模块
                    with gr.Group():
                        gr.Markdown("### 🧪 索引质量自测 (FLAT)")
                        test_recall_btn = gr.Button("🚀 运行召回测试", variant="secondary")
                        test_result_box = gr.Textbox(show_label=False, lines=2)

                with gr.Column(scale=1):
                    # 管理模块
                    with gr.Group():
                        gr.Markdown("### ⚙️ 库管理操作")
                        gr.Markdown("#### 🆕 新建知识库")
                        with gr.Row():
                            new_col_name = gr.Textbox(show_label=False, scale=3)
                            create_btn = gr.Button("创建", variant="secondary", scale=1)
                        create_msg = gr.Label(show_label=False)
                        
                        gr.Markdown("---")
                        gr.Markdown("#### 📄 删除指定文档")
                        with gr.Row():
                            del_file_select = gr.Dropdown(show_label=False, choices=[], scale=3, allow_custom_value=True)
                            btn_del_file = gr.Button("删除文件", variant="stop", scale=1)
                        del_file_msg = gr.Textbox(show_label=False, lines=1, interactive=False)

                        gr.Markdown("---")
                        gr.Markdown("#### 🗑️ 删除知识库")
                        with gr.Row():
                            del_col_select = gr.Dropdown(show_label=False, choices=[], scale=3, allow_custom_value=True)
                            del_btn = gr.Button("删除", variant="stop", scale=1)
                        del_col_msg = gr.Textbox(show_label=False, lines=1, interactive=False)

            # 事件绑定 (移除了 ocr_mode, ocr_lang)
            upload_event = upload_btn.click(
                backend.process_uploaded_pdf, 
                inputs=[files_input, upload_col_select, custom_ocr_token, custom_ocr_url], 
                outputs=[upload_log]
            )
            upload_event.then(
                backend.refresh_all_dropdowns, 
                outputs=[qa_col_select, upload_col_select, del_col_select]
            ).then(
                backend.update_file_list, 
                inputs=[qa_col_select], 
                outputs=[qa_file_select]
            )
            
            create_btn.click(
                backend.create_collection_ui, 
                inputs=[new_col_name], 
                outputs=[upload_col_select, create_msg]
            ).then(
                backend.refresh_all_dropdowns, 
                outputs=[qa_col_select, upload_col_select, del_col_select]
            )

            btn_del_file.click(
                fn=backend.delete_single_file,
                inputs=[upload_col_select, del_file_select],
                outputs=[del_file_msg]
            ).then(
                fn=backend.update_file_list_for_delete,
                inputs=[upload_col_select],
                outputs=[del_file_select]
            )
            upload_col_select.change(
                backend.update_file_list_for_delete,
                inputs=[upload_col_select],
                outputs=[del_file_select]
            )

            del_btn.click(
                backend.delete_collection_ui,
                inputs=[del_col_select],
                outputs=[upload_col_select, del_col_msg] 
            ).then(
                backend.refresh_all_dropdowns, 
                outputs=[qa_col_select, upload_col_select, del_col_select]
            )
            
            test_recall_btn.click(backend.run_recall_test, inputs=[upload_col_select], outputs=[test_result_box])

        # === 标签页 3: 系统配置 ===
        with gr.TabItem("⚙️ 系统配置"):
            with gr.Group():
                gr.Markdown("### 🔌 连接设置")
                use_local_mode = gr.Checkbox(
                    label="📂 启用本地离线模式 (Milvus Lite)", 
                    value=False,
                    info="勾选后，数据将保存在本地 .db 文件中，无需 Milvus 服务器。"
                )
                
                with gr.Row():
                    tk_aistudio = gr.Textbox(
                        label="AISTUDIO_ACCESS_TOKEN", 
                        type="password", 
                        value=os.getenv("AISTUDIO_ACCESS_TOKEN", ""), 
                        scale=1,
                        info="[获取 AI Studio Token](https://aistudio.baidu.com/account/accessToken)"
                    )
                    tk_qianfan = gr.Textbox(
                        label="QIANFAN_API_KEY", 
                        type="password", 
                        value=os.getenv("QIANFAN_API_KEY", ""), 
                        scale=1,
                        info="[获取千帆 API Key](https://console.bce.baidu.com/qianfan/ais/console/apiKey)"
                    )
                
                with gr.Row():
                    tk_uri = gr.Textbox(
                        label="MILVUS_URI", 
                        value=os.getenv("MILVUS_URI", ""), 
                        placeholder="例如: http://localhost:19530", 
                        scale=1,
                        info="[Zilliz Cloud-Clusters-Public Endpoint](https://cloud.zilliz.com/)"
                    )
                    tk_token = gr.Textbox(
                        label="MILVUS_TOKEN", 
                        type="password", 
                        value=os.getenv("MILVUS_TOKEN", ""), 
                        scale=1,
                        info="[获取Zilliz Cloud-Clusters-Token](https://cloud.zilliz.com/)"
                    )
                
                btn_connect = gr.Button("连接 / 初始化系统", variant="primary")
                connect_log = gr.Textbox(label="系统状态", interactive=False, lines=2)

                def toggle_mode(is_local):
                    if is_local:
                        return (
                            gr.update(value="./my_knowledge_base.db", interactive=False, label="本地数据库路径"), 
                            gr.update(value="", interactive=False, placeholder="本地模式无需 Token")
                        )
                    else:
                        return (
                            gr.update(value=os.getenv("MILVUS_URI", ""), interactive=True, label="MILVUS_URI"), 
                            gr.update(value=os.getenv("MILVUS_TOKEN", ""), interactive=True, placeholder="")
                        )

                use_local_mode.change(toggle_mode, inputs=[use_local_mode], outputs=[tk_uri, tk_token])

                btn_connect.click(
                    backend.initialize_system, 
                    inputs=[tk_aistudio, tk_qianfan, tk_uri, tk_token], 
                    outputs=[connect_log, qa_col_select, upload_col_select, del_col_select]
                )

def find_free_port(start=7860):
    for port in range(start, start+10):
        try:
            s = socket.socket()
            s.bind(('', port))
            s.close()
            return port
        except OSError: continue
    return start

if __name__ == "__main__":
    port = find_free_port()
    print(f"🚀 启动 UI: http://127.0.0.1:{port}")
    demo.launch(server_name="127.0.0.1", server_port=port, inbrowser=True)
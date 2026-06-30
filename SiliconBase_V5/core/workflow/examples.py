#!/usr/bin/env python3
"""
Workflow 模块使用示例
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
展示如何定义、执行和修改工作流
"""

from core.workflow import WorkflowDefinition, WorkflowStep, get_perception_fusion, get_workflow_engine


async def example_1_simple_workflow():
    """示例1: 简单工作流 - 打开应用"""

    engine = get_workflow_engine()

    workflow = WorkflowDefinition(
        workflow_id="simple_launch_app",
        name="打开网易云音乐",
        description="查找并启动网易云音乐应用",
        steps=[
            WorkflowStep(
                step_id="check_installed",
                name="检查是否已安装",
                description="检查网易云音乐是否已安装",
                tool_id="system_info",
                tool_params={"check_app": "网易云音乐"},
                step_category="check",
                is_critical=False  # 非关键步骤
            ),
            WorkflowStep(
                step_id="launch_app",
                name="启动应用",
                description="启动网易云音乐",
                tool_id="launch_app",
                tool_params={"app_name": "网易云音乐"},
                outputs={"pid": "$launch_app.pid", "window": "$launch_app.window"},
                step_category="launch",
                is_critical=True,  # 关键步骤
                requires_confirmation=False
            ),
            WorkflowStep(
                step_id="verify_window",
                name="验证窗口",
                description="截图验证窗口是否正常显示",
                tool_id="visual_understand",
                tool_params={
                    "image_source": "screenshot",
                    "question": "网易云音乐窗口是否已正常打开？"
                },
                step_category="verify",
                is_critical=False
            )
        ],
        perception_config={
            "screenshot_before_step": [],
            "screenshot_after_step": ["launch_app"],
            "verification_required": ["launch"]
        }
    )

    # 注册工作流
    engine.create_workflow(workflow)
    print(f"✓ 工作流已创建: {workflow.workflow_id}")

    # 执行（Phase 8: 异步入口）
    execution_id = await engine.execute_workflow(
        workflow_id="simple_launch_app",
        initial_vars={},
        mode="default"
    )

    print(f"✓ 执行实例: {execution_id}")

    # 查询状态
    status = engine.get_execution_status(execution_id)
    print(f"✓ 执行状态: {status}")

    return execution_id


def example_2_data_pipeline():
    """示例2: 数据管道工作流 - 获取比特币价格并生成表格"""

    engine = get_workflow_engine()

    workflow = WorkflowDefinition(
        workflow_id="bitcoin_to_excel",
        name="获取比特币行情并生成Excel",
        description="从网页获取比特币价格数据，处理后生成Excel表格",
        steps=[
            WorkflowStep(
                step_id="fetch_data",
                name="获取网页数据",
                description="从CoinMarketCap获取比特币行情页面",
                tool_id="web_fetch",
                tool_params={
                    "url": "https://coinmarketcap.com/currencies/bitcoin/",
                    "timeout": 15
                },
                outputs={"html_content": "$fetch_data.content", "status_code": "$fetch_data.status"},
                step_category="fetch",
                is_critical=True
            ),
            WorkflowStep(
                step_id="parse_data",
                name="解析数据",
                description="从HTML中提取价格、涨跌幅等数据",
                tool_id="web_parse",
                inputs={"html": "$html_content"},  # 引用变量
                tool_params={
                    "selectors": {
                        "price": ".price-value",
                        "change_24h": ".change-24h",
                        "market_cap": ".market-cap"
                    }
                },
                outputs={"price_data": "$parse_data.result"},
                step_category="transform",
                is_critical=True
            ),
            WorkflowStep(
                step_id="transform_data",
                name="转换数据格式",
                description="将解析的数据转换为DataFrame格式",
                tool_id="code_generate",
                inputs={"data": "$price_data"},
                tool_params={
                    "language": "python",
                    "code_template": """
import pandas as pd
import json

# 输入数据
data = $data

# 转换为DataFrame
df = pd.DataFrame([data])
df['timestamp'] = pd.Timestamp.now()
df['source'] = 'CoinMarketCap'

# 输出
result = df.to_dict('records')[0]
"""
                },
                outputs={"transformed_data": "$transform_data.result"},
                step_category="transform",
                is_critical=True
            ),
            WorkflowStep(
                step_id="generate_excel",
                name="生成Excel文件",
                description="生成Excel表格文件",
                tool_id="code_generate",
                inputs={"data": "$transformed_data"},
                tool_params={
                    "language": "python",
                    "code_template": """
import pandas as pd
from datetime import datetime

# 创建DataFrame
df = pd.DataFrame([$data])

# 生成文件名
filename = f"bitcoin_price_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

# 保存Excel
df.to_excel(filename, index=False, engine='openpyxl')

result = {"file_path": filename, "row_count": len(df)}
"""
                },
                outputs={"excel_file": "$generate_excel.file_path"},
                step_category="save",
                is_critical=True,
                requires_confirmation=True  # 保存前需要确认
            ),
            WorkflowStep(
                step_id="verify_file",
                name="验证文件",
                description="截图验证Excel文件是否正确生成",
                tool_id="visual_understand",
                inputs={"file": "$excel_file"},
                tool_params={
                    "image_source": "screenshot",
                    "question": "Excel表格是否显示比特币价格数据？数据是否正确？"
                },
                step_category="verify",
                is_critical=False
            )
        ],
        variables={  # 默认变量
            "output_dir": "./output",
            "currency": "USD"
        },
        perception_config={
            "enable_visual": True,
            "screenshot_before_step": ["generate_excel"],
            "screenshot_after_step": ["fetch_data", "generate_excel"],
            "verification_required": ["transform", "save"]
        }
    )

    engine.create_workflow(workflow)
    print(f"✓ 数据管道工作流已创建: {workflow.workflow_id}")

    return workflow.workflow_id


def example_3_conditional_workflow():
    """示例3: 条件分支工作流"""

    engine = get_workflow_engine()

    workflow = WorkflowDefinition(
        workflow_id="conditional_example",
        name="智能文件处理",
        description="根据文件类型选择不同的处理方式",
        steps=[
            WorkflowStep(
                step_id="check_file_type",
                name="检查文件类型",
                description="检查输入文件的类型",
                tool_id="file_manager",
                tool_params={"action": "get_info", "path": "$input_file"},
                outputs={"file_type": "$check_file_type.type", "file_size": "$check_file_type.size"},
                step_category="check",
                is_critical=True
            ),
            WorkflowStep(
                step_id="process_excel",
                name="处理Excel文件",
                description="如果是Excel文件，进行数据处理",
                tool_id="code_generate",
                inputs={"file": "$input_file"},
                tool_params={"language": "python", "action": "process_excel"},
                condition="$file_type == 'xlsx' or $file_type == 'xls'",  # 条件
                step_category="transform",
                is_critical=False
            ),
            WorkflowStep(
                step_id="process_csv",
                name="处理CSV文件",
                description="如果是CSV文件，进行数据处理",
                tool_id="code_generate",
                inputs={"file": "$input_file"},
                tool_params={"language": "python", "action": "process_csv"},
                condition="$file_type == 'csv'",  # 条件
                step_category="transform",
                is_critical=False
            ),
            WorkflowStep(
                step_id="convert_format",
                name="转换格式",
                description="转换为标准格式",
                tool_id="code_generate",
                step_category="transform",
                is_critical=True
            )
        ]
    )

    engine.create_workflow(workflow)
    print(f"✓ 条件分支工作流已创建: {workflow.workflow_id}")


def example_4_user_modification():
    """示例4: 用户中途修改工作流"""

    engine = get_workflow_engine()

    # 假设工作流已在执行并处于PAUSED状态
    execution_id = "exec_example_123"

    # 查询可修改内容
    status = engine.get_execution_status(execution_id)
    if status.get("can_modify"):
        print("工作流可以修改")

        # 修改参数
        modifications = {
            # 修改步骤参数
            "modify_params": {
                "generate_excel": {
                    "code_template": """
import pandas as pd
# 添加更多列
data = $data
data['timestamp'] = pd.Timestamp.now()
data['source'] = 'CoinMarketCap'
data['note'] = '用户自定义备注'
df = pd.DataFrame([data])
df.to_excel('bitcoin_full.xlsx', index=False)
"""
                }
            },
            # 添加新步骤
            "add_steps": [
                {
                    "index": 4,
                    "step": {
                        "step_id": "add_chart",
                        "name": "添加图表",
                        "description": "在Excel中添加价格趋势图",
                        "tool_id": "code_generate",
                        "tool_params": {"action": "add_chart"},
                        "step_category": "transform",
                        "is_critical": False
                    }
                }
            ],
            # 更新变量
            "update_variables": {
                "custom_title": "比特币行情报告",
                "include_history": True
            }
        }

        # 应用修改
        success = engine.modify_execution(execution_id, modifications)
        if success:
            print("✓ 修改已应用")

            # 恢复执行
            engine.resume_execution(execution_id)
            print("✓ 工作流已恢复")


async def example_5_perception_fusion():
    """示例5: 感知融合使用"""

    fusion = get_perception_fusion()

    # 1. 基础感知捕获
    print("基础感知捕获:")
    ctx = await fusion.capture(
        enable_visual=True,
        enable_system=True,
        visual_question="当前屏幕显示什么内容？"
    )
    print(f"  视觉描述: {ctx.visual.description[:100] if ctx.visual else 'N/A'}...")
    print(f"  CPU: {ctx.system.cpu_percent if ctx.system else 'N/A'}%")

    # 2. 针对步骤的智能感知
    print("\n针对步骤的感知:")
    ctx = await fusion.capture_for_step(
        step_category="launch",
        step_goal="启动网易云音乐"
    )
    print(f"  描述: {ctx.visual.description[:100] if ctx.visual else 'N/A'}...")

    # 3. 结果验证
    print("\n结果验证:")
    from core.workflow import ExpectedOutcome

    expected = ExpectedOutcome(
        visual_indicator="网易云音乐窗口已打开",
        file_existence="bitcoin_price.xlsx"
    )

    result = fusion.verify(expected, ctx, {"success": True})
    print(f"  验证通过: {result.all_passed}")
    print(f"  详情: {result.details}")


def example_6_state_machine():
    """示例6: 状态机使用"""
    from core.workflow import StateEvent, WorkflowStateMachine

    # 创建状态机
    sm = WorkflowStateMachine("exec_test_123")

    # 注册钩子
    def on_pause(state_machine, state_name, event):
        print(f"工作流已暂停: {event.payload.get('reason', '')}")

    sm.on_enter("PAUSED", on_pause)

    # 状态转换
    sm.transition(StateEvent.start())  # PENDING -> RUNNING
    sm.transition(StateEvent.pause("需要用户确认"))  # RUNNING -> PAUSED

    print(f"当前状态: {sm.state_name}")
    print(f"状态历史: {sm.get_state_history()}")

    # 恢复
    sm.transition(StateEvent.modify({"update": "something"}))  # PAUSED -> MODIFIED -> RUNNING


if __name__ == "__main__":
    print("=" * 60)
    print("Workflow 模块使用示例")
    print("=" * 60)

    # 运行示例
    try:
        example_1_simple_workflow()
    except Exception as e:
        print(f"示例1错误: {e}")

    print("\n" + "=" * 60)

    try:
        example_2_data_pipeline()
    except Exception as e:
        print(f"示例2错误: {e}")

    print("\n所有示例运行完成")

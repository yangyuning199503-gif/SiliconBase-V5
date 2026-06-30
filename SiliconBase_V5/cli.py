#!/usr/bin/env python3
"""
SiliconBase V5 - 命令行工具
提供简洁的命令行接口使用所有功能
"""
import argparse
import json
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from siliconbase_client import ClientConfig, SiliconBaseClient


def main():
    parser = argparse.ArgumentParser(
        description="SiliconBase V5 - 硅基生命底座客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 快速对话
  python cli.py "帮我打开浏览器"

  # 交互模式
  python cli.py -i

  # 使用OpenAI
  python cli.py --provider openai --model gpt-4 "你好"

  # 列出可用工具
  python cli.py --list-tools

  # 执行特定工具
  python cli.py --tool launch_app --params '{"app_name": "chrome"}'

  # 语音交互模式
  python cli.py --voice -i
        """
    )

    # 基本配置
    parser.add_argument("--provider", "-p", default="ollama",
                       choices=["ollama", "openai", "anthropic", "deepseek"],
                       help="AI Provider (默认: ollama)")
    parser.add_argument("--model", "-m", default="qwen3:8b",
                       help="AI Model (默认: qwen3:8b)")
    parser.add_argument("--voice", "-v", action="store_true",
                       help="启用语音功能")
    parser.add_argument("--no-memory", action="store_true",
                       help="禁用记忆系统")
    parser.add_argument("--no-tools", action="store_true",
                       help="禁用工具调用")

    # 运行模式
    parser.add_argument("--interactive", "-i", action="store_true",
                       help="交互模式")
    parser.add_argument("--stream", "-s", action="store_true",
                       help="流式输出")
    parser.add_argument("message", nargs="?", help="要发送的消息")

    # 工具相关
    parser.add_argument("--list-tools", "-lt", action="store_true",
                       help="列出所有可用工具")
    parser.add_argument("--tool", "-t", help="执行指定工具")
    parser.add_argument("--params", help="工具参数 (JSON格式)")

    # 记忆相关
    parser.add_argument("--remember", help="添加记忆内容")
    parser.add_argument("--recall", help="检索记忆")
    parser.add_argument("--clear-memory", action="store_true",
                       help="清空对话记忆")

    # 会话管理
    parser.add_argument("--new-session", action="store_true",
                       help="创建新会话")
    parser.add_argument("--session-id", help="指定会话ID")
    parser.add_argument("--info", action="store_true",
                       help="显示会话信息")

    args = parser.parse_args()

    # 创建配置
    config = ClientConfig(
        ai_provider=args.provider,
        ai_model=args.model,
        voice_enabled=args.voice,
        memory_enabled=not args.no_memory,
        tools_enabled=not args.no_tools,
        session_id=args.session_id or "default"
    )

    # 初始化客户端
    client = SiliconBaseClient(config)

    try:
        # 处理各种命令
        if args.list_tools:
            print_tools(client)

        elif args.tool:
            execute_tool_command(client, args.tool, args.params)

        elif args.remember:
            client.remember(args.remember)
            print(f"✅ 已记住: {args.remember}")

        elif args.recall:
            memories = client.recall(args.recall)
            print_memories(memories)

        elif args.clear_memory:
            client.clear_memory()
            print("✅ 记忆已清空")

        elif args.info:
            print_session_info(client)

        elif args.new_session:
            session_id = client.new_session()
            print(f"✅ 新会话创建: {session_id}")

        elif args.interactive:
            interactive_mode(client, args.stream)

        elif args.message:
            # 直接对话
            if args.stream:
                stream_chat(client, args.message)
            else:
                response = client.chat(args.message)
                print(f"🤖 {response.content}")

        else:
            parser.print_help()

    except KeyboardInterrupt:
        print("\n👋 再见！")
    except Exception as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


def print_tools(client: SiliconBaseClient):
    """打印工具列表"""
    tools = client.list_tools()

    print("\n" + "=" * 60)
    print(f"🔧 可用工具列表 (共 {len(tools)} 个)")
    print("=" * 60)

    for i, tool in enumerate(tools, 1):
        print(f"\n{i}. {tool['name']}")
        print(f"   描述: {tool['description']}")
        if tool.get('parameters'):
            print(f"   参数: {json.dumps(tool['parameters'], ensure_ascii=False, indent=4)}")


def execute_tool_command(client: SiliconBaseClient, tool_name: str, params_str: str):
    """执行工具命令"""
    try:
        params = json.loads(params_str) if params_str else {}
        result = client.execute_tool(tool_name, params)
        print("✅ 工具执行结果:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print("❌ 参数JSON格式错误")
    except Exception as e:
        print(f"❌ 工具执行失败: {e}")


def print_memories(memories: list):
    """打印记忆列表"""
    if not memories:
        print("📝 没有找到相关记忆")
        return

    print("\n" + "=" * 60)
    print(f"📝 找到 {len(memories)} 条相关记忆")
    print("=" * 60)

    for i, mem in enumerate(memories, 1):
        print(f"\n{i}. {mem.get('content', 'N/A')}")
        print(f"   时间: {mem.get('timestamp', 'N/A')}")
        print(f"   层级: {mem.get('level', 'N/A')}")


def print_session_info(client: SiliconBaseClient):
    """打印会话信息"""
    info = client.get_session_info()

    print("\n" + "=" * 60)
    print("📊 会话信息")
    print("=" * 60)
    print(f"会话ID: {info['session_id']}")
    print(f"历史消息: {info['history_count']} 条")
    print(f"AI Provider: {info['ai_provider']}")
    print(f"AI Model: {info['ai_model']}")
    print(f"语音功能: {'✅' if info['voice_enabled'] else '❌'}")
    print(f"记忆功能: {'✅' if info['memory_enabled'] else '❌'}")


def stream_chat(client: SiliconBaseClient, message: str):
    """流式对话"""
    print("🤖 ", end="", flush=True)
    try:
        for chunk in client.chat(message, stream=True):
            print(chunk, end="", flush=True)
        print()
    except Exception as e:
        print(f"\n❌ 流式输出失败: {e}")


def interactive_mode(client: SiliconBaseClient, stream: bool = False):
    """交互模式"""
    import signal

    # 处理Ctrl+C
    def signal_handler(sig, frame):
        print("\n👋 再见！")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    print("\n" + "=" * 60)
    print("🤖 SiliconBase V5 - 交互模式")
    print("=" * 60)
    print("命令:")
    print("  /help    - 显示帮助")
    print("  /tools   - 列出工具")
    print("  /clear   - 清空记忆")
    print("  /info    - 会话信息")
    print("  /quit    - 退出")
    print("=" * 60)
    print()

    while True:
        try:
            user_input = input("👤 你: ").strip()

            if not user_input:
                continue

            # 处理命令
            if user_input.startswith("/"):
                cmd = user_input[1:].lower()

                if cmd in ["quit", "exit", "q"]:
                    print("👋 再见！")
                    break

                elif cmd == "help":
                    print_help()

                elif cmd == "tools":
                    print_tools(client)

                elif cmd == "clear":
                    client.clear_memory()
                    print("✅ 记忆已清空")

                elif cmd == "info":
                    print_session_info(client)

                else:
                    print(f"❌ 未知命令: {cmd}")

                continue

            # 普通对话
            if stream:
                print("🤖 ", end="", flush=True)
                for chunk in client.chat(user_input, stream=True):
                    print(chunk, end="", flush=True)
                print()
            else:
                response = client.chat(user_input)
                print(f"🤖 {response.content}")

        except KeyboardInterrupt:
            print("\n👋 再见！")
            break
        except Exception as e:
            print(f"❌ 错误: {e}")


def print_help():
    """打印交互模式帮助"""
    print("""
命令列表:
  /help    - 显示此帮助
  /tools   - 列出所有可用工具
  /clear   - 清空对话记忆
  /info    - 显示会话信息
  /quit    - 退出程序

快捷键:
  Ctrl+C   - 退出程序
    """)


if __name__ == "__main__":
    main()

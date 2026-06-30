#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SiliconBase V5 - 安装配置
"""
from setuptools import setup, find_packages
from pathlib import Path

# 读取README
readme_path = Path(__file__).parent / "SiliconBase_V5" / "README.md"
long_description = readme_path.read_text(encoding='utf-8') if readme_path.exists() else ""

# 读取requirements
requirements_path = Path(__file__).parent / "SiliconBase_V5" / "requirements.txt"
requirements = []
if requirements_path.exists():
    requirements = requirements_path.read_text().strip().split('\n')

setup(
    name="siliconbase",
    version="5.0.0",
    description="SiliconBase V5 - 硅基生命底座，通用AI客户端",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="SiliconBase Team",
    author_email="team@siliconbase.ai",
    url="https://github.com/siliconbase/siliconbase-v5",
    
    # 包配置
    packages=find_packages(where="SiliconBase_V5"),
    package_dir={"": "SiliconBase_V5"},
    
    # 包含数据文件
    package_data={
        "": [
            "*.yaml", "*.json", "*.md",
            "frontend/dist/*",
            "models/*",
        ],
    },
    
    # 依赖
    install_requires=requirements or [
        "fastapi>=0.100.0",
        "uvicorn>=0.23.0",
        "websockets>=11.0",
        "pydantic>=2.0.0",
        "sqlalchemy>=2.0.0",
        "psycopg2-binary>=2.9.0",
        "redis>=4.6.0",
        "httpx>=0.24.0",
        "requests>=2.31.0",
        "numpy>=1.24.0",
        "pillow>=10.0.0",
        "pyautogui>=0.9.54",
        "pyperclip>=1.8.2",
        "vosk>=0.3.45",
        "pyaudio>=0.2.13",
        "edge-tts>=6.1.0",
        "pyttsx3>=2.90",
        "schedule>=1.2.0",
        "psutil>=5.9.0",
        "pywin32>=306; platform_system=='Windows'",
    ],
    
    # 可选依赖
    extras_require={
        "full": [
            "torch>=2.0.0",
            "transformers>=4.30.0",
            "sentence-transformers>=2.2.0",
            "opencv-python>=4.8.0",
            "easyocr>=1.7.0",
            "piper-tts>=1.2.0",
        ],
        "dev": [
            "pytest>=7.4.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.5.0",
        ],
    },
    
    # 入口点
    entry_points={
        "console_scripts": [
            "siliconbase=SiliconBase_V5.cli:main",
            "sbv5=SiliconBase_V5.cli:main",
        ],
    },
    
    # 分类
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    
    python_requires=">=3.10",
    
    # 项目URL
    project_urls={
        "Bug Reports": "https://github.com/siliconbase/siliconbase-v5/issues",
        "Source": "https://github.com/siliconbase/siliconbase-v5",
        "Documentation": "https://docs.siliconbase.ai",
    },
    
    keywords="ai llm ollama openai voice automation agent tools",
    zip_safe=False,
)

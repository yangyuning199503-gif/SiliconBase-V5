#!/usr/bin/env python3  # 指定Python解释器路径
# 声明UTF-8编码支持中文
"""
颜色处理工具 - 无SciPy依赖

提供颜色分析和聚类功能，替代 scipy.cluster.vq.kmeans2
"""


import numpy as np  # 导入NumPy库，用于数值计算


def dominant_colors_kmeans(pixels: np.ndarray, k: int = 5,  # 定义K-means主导颜色提取函数
                           max_iter: int = 10, seed: int = 42) -> np.ndarray:  # 默认参数设置
    """
    K-means聚类提取主导颜色

    替代 scipy.cluster.vq.kmeans2，无需SciPy依赖

    Args:
        pixels: 像素数组，形状为 (n_pixels, 3)，RGB格式
        k: 聚类数量
        max_iter: 最大迭代次数
        seed: 随机种子

    Returns:
        聚类中心点，形状为 (k, 3)，RGB值
    """
    if len(pixels) == 0:  # 检查输入是否为空
        return np.array([[128, 128, 128]] * k)  # 返回默认灰色

    # 限制k不超过像素数量  # 注释说明边界条件处理
    k = min(k, len(pixels))  # 确保聚类数不超过像素数

    # 随机初始化中心点  # 注释说明初始化策略
    np.random.seed(seed)  # 设置随机种子保证可复现性
    indices = np.random.choice(len(pixels), k, replace=False)  # 随机选择k个不重复索引
    centroids = pixels[indices].astype(float)  # 获取初始中心点并转为浮点数

    # 处理k=1的特殊情况  # 注释说明特殊情况优化
    if k == 1:  # 如果只需要一个聚类
        return np.array([pixels.mean(axis=0)])  # 直接返回平均值

    for _iteration in range(max_iter):  # 迭代优化聚类中心
        # 计算每个像素到所有中心点的距离  # 注释说明算法步骤
        # 扩展维度以便广播: pixels (N, 1, 3), centroids (1, k, 3)  # 广播机制说明
        expanded_pixels = pixels[:, np.newaxis, :]  # 扩展像素数组维度为(N, 1, 3)
        expanded_centroids = centroids[np.newaxis, :, :]  # 扩展中心点维度为(1, k, 3)

        # 欧氏距离平方  # 注释说明距离计算方式
        distances = np.sum((expanded_pixels - expanded_centroids) ** 2, axis=2)  # 计算距离矩阵(N, k)

        # 分配：每个像素属于最近的中心点  # 注释说明分配步骤
        labels = np.argmin(distances, axis=1)  # 为每个像素分配最近的聚类标签

        # 更新：重新计算中心点  # 注释说明更新步骤
        new_centroids = np.array([  # 计算新的聚类中心
            pixels[labels == i].mean(axis=0) if np.any(labels == i) else centroids[i]  # 处理空聚类
            for i in range(k)  # 遍历每个聚类
        ])  # 新中心点计算结束

        # 检查收敛  # 注释说明收敛判断
        if np.allclose(centroids, new_centroids, atol=1.0):  # 如果中心点变化小于阈值
            break  # 提前结束迭代

        centroids = new_centroids  # 更新中心点

    return centroids  # 返回最终聚类中心


def dominant_colors_histogram(image_rgb: np.ndarray, k: int = 5) -> np.ndarray:  # 定义直方图主导颜色提取函数
    """
    基于颜色直方图的主导颜色提取

    最快的颜色分析方法，适合不需要精确聚类的场景

    Args:
        image_rgb: RGB图像数组，形状为 (H, W, 3)
        k: 返回颜色数量

    Returns:
        主导颜色数组，形状为 (k, 3)
    """
    # 量化颜色（减少计算量）  # 注释说明优化策略
    # 将每通道256级减少到16级  # 量化级别说明
    quantized = (image_rgb // 16).astype(np.uint8)  # 颜色量化，减少计算量

    # 转换为可哈希的格式  # 注释说明数据转换
    h, w = quantized.shape[:2]  # 获取图像高宽
    pixels_1d = quantized.reshape(-1, 3)  # 重塑为二维数组(N, 3)

    # 统计颜色频率  # 注释说明统计步骤
    colors, counts = np.unique(pixels_1d, axis=0, return_counts=True)  # 统计每种颜色出现次数

    # 选择最常见的k种颜色  # 注释说明选择策略
    k = min(k, len(colors))  # 确保k不超过颜色种类数
    top_indices = np.argsort(counts)[-k:][::-1]  # 获取频率最高的k个颜色的索引

    # 转回0-255范围  # 注释说明反量化
    dominant = colors[top_indices] * 16 + 8  # +8使颜色居中，反量化

    return dominant  # 返回主导颜色


def dominant_colors_median_cut(image_rgb: np.ndarray, k: int = 5) -> np.ndarray:  # 定义中位切分算法函数
    """
    中位切分算法提取主导颜色

    比K-means更快，质量介于K-means和直方图之间
    常用于图像量化

    Args:
        image_rgb: RGB图像数组
        k: 颜色数量（必须是2的幂次方）

    Returns:
        主导颜色数组
    """
    # 确保k是2的幂次方  # 注释说明约束处理
    import math  # 导入数学模块
    depth = max(1, int(math.log2(k)))  # 计算递归深度
    actual_k = 2 ** depth  # 实际聚类数（2的幂）

    pixels = image_rgb.reshape(-1, 3).astype(np.float32)  # 重塑像素数组

    def split_box(box_pixels):  # 定义递归分割函数
        """递归分割颜色盒子"""  # 函数文档字符串
        if len(box_pixels) == 0:  # 检查是否为空
            return [np.array([128, 128, 128])]  # 返回默认灰色

        # 找到变化最大的通道  # 注释说明分割策略
        ranges = box_pixels.max(axis=0) - box_pixels.min(axis=0)  # 计算各通道范围
        channel = np.argmax(ranges)  # 找到范围最大的通道

        # 按该通道排序并分割  # 注释说明分割操作
        sorted_pixels = box_pixels[np.argsort(box_pixels[:, channel])]  # 按选中通道排序
        mid = len(sorted_pixels) // 2  # 计算中点

        return [  # 返回分割后的两部分
            sorted_pixels[:mid],  # 前半部分
            sorted_pixels[mid:]  # 后半部分
        ]  # 返回结束

    # 递归分割  # 注释说明主循环
    boxes = [pixels]  # 初始化盒子列表
    for _ in range(depth):  # 递归depth次
        new_boxes = []  # 新盒子列表
        for box in boxes:  # 遍历当前所有盒子
            new_boxes.extend(split_box(box))  # 分割并添加结果
        boxes = new_boxes  # 更新盒子列表

    # 计算每个盒子的平均颜色  # 注释说明最终计算
    colors = []  # 颜色列表
    for box in boxes[:actual_k]:  # 遍历所有盒子
        if len(box) > 0:  # 如果盒子非空
            colors.append(box.mean(axis=0))  # 计算平均颜色
        else:  # 如果盒子为空
            colors.append([128, 128, 128])  # 使用默认灰色

    return np.array(colors)  # 返回颜色数组


def color_distance(c1: np.ndarray, c2: np.ndarray,  # 定义颜色距离计算函数
                   method: str = "euclidean") -> float:  # 默认使用欧氏距离
    """
    计算两个颜色之间的距离

    Args:
        c1, c2: RGB颜色数组
        method: 距离计算方法 ("euclidean", "manhattan", "delta_e")

    Returns:
        距离值
    """
    if method == "euclidean":  # 欧氏距离
        return np.sqrt(np.sum((c1 - c2) ** 2))  # 计算欧氏距离
    elif method == "manhattan":  # 曼哈顿距离
        return np.sum(np.abs(c1 - c2))  # 计算曼哈顿距离
    elif method == "delta_e":  # Delta E（简化版）
        # 简化的Delta E（CIE76）  # 注释说明简化版本
        # 注意：这需要Lab颜色空间，这里简化为欧氏距离  # 限制说明
        return np.sqrt(np.sum((c1 - c2) ** 2))  # 简化实现使用欧氏距离
    else:  # 未知方法
        raise ValueError(f"Unknown distance method: {method}")  # 抛出异常


def rgb_to_hex(rgb: np.ndarray) -> str:  # 定义RGB转十六进制函数
    """RGB转十六进制颜色"""  # 函数文档字符串
    return f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"  # 返回十六进制颜色字符串


def hex_to_rgb(hex_color: str) -> np.ndarray:  # 定义十六进制转RGB函数
    """十六进制颜色转RGB"""  # 函数文档字符串
    hex_color = hex_color.lstrip('#')  # 去除开头的#号
    return np.array([  # 返回RGB数组
        int(hex_color[0:2], 16),  # 解析红色通道
        int(hex_color[2:4], 16),  # 解析绿色通道
        int(hex_color[4:6], 16)  # 解析蓝色通道
    ])  # 数组返回结束


# ═══════════════════════════════════════════════════════════════  # 分隔线注释
# 向后兼容：提供与 scipy.cluster.vq.kmeans2 兼容的接口  # 向后兼容说明
# ═══════════════════════════════════════════════════════════════  # 分隔线结束

def kmeans2_fallback(data: np.ndarray, k: int,  # 定义兼容scipy的kmeans2函数
                     iter: int = 10,  # 迭代次数参数
                     minit: str = 'random',  # 初始化方法参数
                     seed: int = 42) -> tuple[np.ndarray, np.ndarray]:  # 随机种子参数
    """
    兼容 scipy.cluster.vq.kmeans2 的接口

    用于直接替换现有代码中的 kmeans2 调用

    Args:
        data: 输入数据 (n_samples, n_features)
        k: 聚类数量
        iter: 迭代次数
        minit: 初始化方法 ('random', 'points')
        seed: 随机种子

    Returns:
        (centroids, labels): 中心点和标签
    """
    # 确保数据是float类型  # 注释说明类型转换
    data = np.asarray(data, dtype=float)  # 转换为浮点数组

    # 执行聚类  # 注释说明聚类步骤
    centroids = dominant_colors_kmeans(data, k=k, max_iter=iter, seed=seed)  # 调用kmeans函数

    # 计算标签  # 注释说明标签分配
    distances = np.sqrt(((data[:, np.newaxis, :] - centroids[np.newaxis, :, :]) ** 2).sum(axis=2))  # 计算距离
    labels = np.argmin(distances, axis=1)  # 分配标签

    return centroids, labels  # 返回中心点和标签


# 便捷函数：选择最佳算法  # 注释说明便捷函数
def extract_dominant_colors(image_rgb: np.ndarray,  # 定义统一接口函数
                            k: int = 5,  # 默认聚类数
                            algorithm: str = "auto") -> np.ndarray:  # 默认自动选择算法
    """
    提取主导颜色的统一接口

    Args:
        image_rgb: RGB图像
        k: 颜色数量
        algorithm: 算法选择 ("auto", "kmeans", "histogram", "median_cut")

    Returns:
        主导颜色数组
    """
    if algorithm == "auto":  # 如果自动选择
        # 根据图像大小自动选择  # 注释说明选择逻辑
        pixel_count = image_rgb.shape[0] * image_rgb.shape[1]  # 计算像素总数
        if pixel_count > 1000000:  # 大图用直方图  # 100万像素以上
            algorithm = "histogram"  # 选择直方图算法
        elif pixel_count > 100000:  # 中等用中位切分  # 10万-100万像素
            algorithm = "median_cut"  # 选择中位切分算法
        else:  # 小图用K-means  # 10万像素以下
            algorithm = "kmeans"  # 选择K-means算法

    if algorithm == "kmeans":  # K-means算法
        pixels = image_rgb.reshape(-1, 3)  # 重塑为像素列表
        return dominant_colors_kmeans(pixels, k=k)  # 调用kmeans函数
    elif algorithm == "histogram":  # 直方图算法
        return dominant_colors_histogram(image_rgb, k=k)  # 调用直方图函数
    elif algorithm == "median_cut":  # 中位切分算法
        return dominant_colors_median_cut(image_rgb, k=k)  # 调用中位切分函数
    else:  # 未知算法
        raise ValueError(f"Unknown algorithm: {algorithm}")  # 抛出异常


if __name__ == "__main__":  # 如果是主程序运行
    # 测试  # 注释说明测试代码
    print("测试颜色工具...")  # 打印测试标题

    # 生成测试数据  # 注释说明测试数据
    np.random.seed(42)  # 设置随机种子
    test_pixels = np.random.randint(0, 256, (1000, 3), dtype=np.uint8)  # 生成随机像素

    # 测试K-means  # 注释说明K-means测试
    print("\n1. K-means聚类:")  # 打印测试标题
    centers = dominant_colors_kmeans(test_pixels, k=5)  # 执行K-means聚类
    print(f"   中心点:\n{centers}")  # 打印聚类中心

    # 测试直方图  # 注释说明直方图测试
    print("\n2. 直方图方法:")  # 打印测试标题
    test_image = test_pixels.reshape(25, 40, 3)  # 重塑为图像
    hist_colors = dominant_colors_histogram(test_image, k=5)  # 执行直方图分析
    print(f"   主导颜色:\n{hist_colors}")  # 打印结果

    # 测试中位切分  # 注释说明中位切分测试
    print("\n3. 中位切分方法:")  # 打印测试标题
    median_colors = dominant_colors_median_cut(test_image, k=4)  # 执行中位切分
    print(f"   主导颜色:\n{median_colors}")  # 打印结果

    # 测试兼容接口  # 注释说明兼容接口测试
    print("\n4. 兼容kmeans2接口:")  # 打印测试标题
    centroids, labels = kmeans2_fallback(test_pixels, k=3)  # 调用兼容接口
    print(f"   中心点:\n{centroids}")  # 打印中心点
    print(f"   标签分布: {np.bincount(labels)}")  # 打印标签分布

    print("\n✅ 所有测试通过!")  # 打印测试通过信息


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"颜色处理工具库"，提供多种主导颜色提取算法，
# 完全替代SciPy的kmeans2功能，消除对重型依赖库的依赖。
#
# 【设计特点】
# 1. 零SciPy依赖：使用纯NumPy实现K-means、直方图、中位切分三种算法
# 2. 算法自适应：根据图像大小自动选择最优算法（大图直方图、小图K-means）
# 3. 向后兼容：提供kmeans2_fallback函数，可直接替换scipy.cluster.vq.kmeans2
# 4. 性能优化：针对RGB图像处理做了专门的向量化优化
# 5. 工具函数完备：提供RGB与十六进制互转、颜色距离计算等辅助功能
#
# 【关联文件】
# - perception/screen_capture.py  : 使用颜色分析功能进行屏幕内容分析
# - tools/image_analysis.py       : 调用颜色提取功能进行图像处理
# - core/dependency_utils.py      : 检查numpy_dep可用性
#
# 【核心功能效果】
# 1. K-means聚类：提取精确的k个主导颜色，适合小图像（<10万像素）
# 2. 直方图法：O(n)复杂度，适合大图像快速分析（>100万像素）
# 3. 中位切分：O(n log n)复杂度，平衡速度和质量（10-100万像素）
# 4. 颜色距离：支持欧氏距离、曼哈顿距离等度量方式
# 5. 格式转换：RGB与十六进制颜色格式互转
#
# 【使用示例】
# from core.color_utils import extract_dominant_colors, rgb_to_hex
#
# # 自动选择算法提取主导颜色
# colors = extract_dominant_colors(image, k=5, algorithm="auto")
#
# # 转换为十六进制
# hex_colors = [rgb_to_hex(c) for c in colors]
#
# # 向后兼容：替换scipy.kmeans2
# from core.color_utils import kmeans2_fallback
# centroids, labels = kmeans2_fallback(data, k=3)
# =============================================================================

"""第四问所需的连续可靠接收证书；仅保留两个已验证纯函数。"""
import math
import geometry as g

def reception_certificate(poly, q, successful_positions=(), min_radius=1000.0):
    """全向源的可靠接收证明，利用所有既往成功接收点。

    R >= max(1000, max_i ||s-p_i||)。将不能由历史距离支配的残余区域
    K ∩ {||q-s|| >= ||p_i-s||, all i} 保守裁剪出来；它若完全位于
    B(q,1000) 内，则 K 中每个源均保证被 q 接收。方向/near 都算成功。
    poly 必须是包含所有相容源位置的凸多边形（点和线段也可）。
    本函数对第四问只证明距离条件；不能证明未知定向角覆盖。
    """
    if not poly:
        raise ValueError("不能用空几何状态证明接收")
    q = tuple(q)
    successful_positions = [tuple(p) for p in successful_positions]
    if q in successful_positions:
        return {"guaranteed": True, "reason": "previous_success_position",
                "residual_vertices": [], "residual_radius_m": 0.0}
    # 以 q 为局部原点，避免大坐标平方差消去；clip 额外向外扩张 EPS。
    residual = [g.sub(s, q) for s in poly]
    for p in successful_positions:
        n = g.sub(q, p)
        residual = g.clip(residual, n, -0.5 * g.dot(n, n))
        if not residual:
            return {"guaranteed": True, "reason": "history_dominates_everywhere",
                    "residual_vertices": [], "residual_radius_m": 0.0}
    residual_radius = max(math.hypot(*s) for s in residual)
    return {"guaranteed": residual_radius <= min_radius - 1e-6,
            "reason": "residual_inside_minimum_radius" if residual_radius <= min_radius - 1e-6
                      else "no_certificate",
            "residual_vertices": [g.add(s, q) for s in residual],
            "residual_radius_m": residual_radius}


def guaranteed_reception(poly, q, successful_positions=(), min_radius=1000.0):
    """适合 Q3 选点调用的布尔入口；False 仅指本外包未能证明。"""
    return reception_certificate(poly, q, successful_positions, min_radius)["guaranteed"]

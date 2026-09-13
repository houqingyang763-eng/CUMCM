"""公开估计中心的开放路线整数DP；不含真值求解或文件入口。"""
from array import array
from fractions import Fraction
import math

SCALE = 1_000_000
INF = 2**62

def distance_floor(a, b):
    """对加载后的binary64坐标精确转有理数，再精确取欧氏距离的微米下界。"""
    dx = Fraction(a[0]) - Fraction(b[0])
    dy = Fraction(a[1]) - Fraction(b[1])
    squared = (dx*dx + dy*dy) * SCALE*SCALE
    return math.isqrt(squared.numerator // squared.denominator)


def shortest_open_path(start, edges):
    """从原点出发、不返回原点的Hamilton路径。输入是整数，组合最优无浮点误差。"""
    n = len(start)
    if n == 0:
        return 0, []
    assert 1 <= n <= 16 and len(edges) == n
    size = 1 << n
    dp = array('q', [INF]) * (size*n)
    parent = array('b', [-1]) * (size*n)
    for j in range(n):
        dp[(1 << j)*n+j] = start[j]
    for mask in range(1, size):
        bitset = mask
        while bitset:
            bit = bitset & -bitset
            j = bit.bit_length()-1
            previous = mask ^ bit
            if previous:
                best, best_i = INF, -1
                remaining = previous
                offset = previous*n
                while remaining:
                    b = remaining & -remaining
                    i = b.bit_length()-1
                    candidate = dp[offset+i] + edges[i][j]
                    if candidate < best:
                        best, best_i = candidate, i
                    remaining ^= b
                dp[mask*n+j], parent[mask*n+j] = best, best_i
            bitset ^= bit
    mask = size-1
    j = min(range(n), key=lambda k: dp[mask*n+k])
    value, order = dp[mask*n+j], []
    while mask:
        order.append(j)
        i = parent[mask*n+j]
        mask ^= 1 << j
        j = i
    return value, list(reversed(order))

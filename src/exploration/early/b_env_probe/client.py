"""B 题接口检查用客户端；不包含搜索策略，不调用 AI 服务。"""
import http.client
import json
import math
import time
import uuid


class ProbeError(RuntimeError):
    pass


class RobotClient:
    def __init__(self, robot_id, port=2026, timeout=5.0, retries=2,
                 transport=None, clock=time.perf_counter, sleep=time.sleep):
        self.robot_id = robot_id
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self.clock = clock
        self.sleep = sleep
        self.transport = transport or self._http
        self.prefix = uuid.uuid4().hex[:12]
        self.sequence = 0
        self.virtual_time = 0.0
        self.deadline = None
        self.failed = False
        self.entered = False
        self.exited = False
        self.records = []

    def _http(self, path, body, timeout):
        # 固定回环地址；不经过系统代理，不访问云端模型。
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        try:
            conn.request('POST', path, body,
                         {'Content-Type': 'application/json; charset=utf-8'})
            response = conn.getresponse()
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ProbeError('响应超过本检查程序的读取上限')
            return response.status, json.loads(raw)
        finally:
            conn.close()

    def action(self, path, position=None, channel=None):
        if self.failed or self.exited:
            raise ProbeError('会话已停止，禁止继续新动作')
        if path not in ('/enter', '/measure', '/clear', '/exit'):
            raise ValueError('未知指令')
        if (path == '/enter') == self.entered:
            raise ProbeError('必须先进入一次，进入后不得重复进入')
        payload = {'arena_id': 'default', 'robot_id': self.robot_id}
        if path in ('/measure', '/clear'):
            if isinstance(channel, bool) or not isinstance(channel, int) or not 1 <= channel <= 20:
                raise ValueError('频道必须是 1—20 的整数')
            if position is None or len(position) != 2:
                raise ValueError('位置必须包含 x、y')
            if any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or abs(v) > 2000000 for v in position):
                raise ValueError('位置必须是范围内的有限数值')
            payload.update(position=dict(zip(('x', 'y'), position)), channel=channel)
        self.sequence += 1
        payload['request_id'] = f'{self.prefix}-{self.sequence}'
        # 在重试循环外编码：每次重试复用完全相同的 ID 和字节。
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        started = self.clock()
        try:
            for attempt in range(self.retries + 1):
                timeout = self.timeout
                if self.deadline is not None:
                    remaining = self.deadline - self.clock()
                    if remaining <= 0:
                        raise ProbeError('已达到本局现实截止时间')
                    timeout = min(timeout, remaining)
                try:
                    status, result = self.transport(path, body, timeout)
                    break
                except (OSError, http.client.HTTPException):
                    if attempt == self.retries:
                        raise
                    delay = 0.1 * (attempt + 1)
                    if self.deadline is not None:
                        delay = min(delay, max(0, self.deadline - self.clock()))
                    self.sleep(delay)
            elapsed = self.clock() - started
            # 不把参赛队号写进日志；只保存调试必需的动作参数。
            self.records.append({'path': path, 'position': position, 'channel': channel,
                                 'request_id': payload['request_id'], 'attempts': attempt + 1,
                                 'elapsed_s': elapsed, 'status': status, 'response': result})
            if status != 200 or not isinstance(result, dict) or result.get('accepted') is not True:
                raise ProbeError(f'动作未接受：HTTP {status}')
            virtual = result.get('virtual_time_s')
            if isinstance(virtual, bool) or not isinstance(virtual, (int, float)) or not math.isfinite(virtual):
                raise ProbeError('非法虚拟时间')
            if virtual < self.virtual_time:
                raise ProbeError('虚拟时间倒退')
            if path == '/enter':
                remaining = result.get('remaining_real_duration_s')
                if isinstance(remaining, bool) or not isinstance(remaining, (int, float)) or not 0 <= remaining <= 1200:
                    raise ProbeError('非法剩余现实时间')
                self.deadline = started + remaining  # 保守扣除请求往返耗时
                self.entered = True
            elif path == '/measure':
                kind = result.get('measure_result')
                if kind not in ('direction', 'near', 'no_signal'):
                    raise ProbeError('未知检测结果')
                if kind == 'direction':
                    angle = result.get('svd_deg')
                    if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not 0 <= angle < 360:
                        raise ProbeError('非法示向度')
            elif path == '/clear' and result.get('clear_result') not in ('success', 'no_target_in_range'):
                raise ProbeError('未知清除结果')
            elif path == '/exit':
                self.exited = True
            self.virtual_time = float(virtual)
            return result
        except Exception:
            # 拒绝、损坏响应或重试耗尽均停止；不猜测结果继续走。
            self.failed = True
            raise

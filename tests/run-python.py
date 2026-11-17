import argparse
import importlib.util
import json
import subprocess
from pathlib import Path
import sys
import time
import unittest


DESCRIPTIONS = json.loads(Path(__file__).with_name('descriptions.zh-CN.json').read_text())

def row(symbol, seconds, description):
    duration = f'{seconds:.2f}s'
    return f'{symbol} {duration:>12}  {description}'


class ReportStream:
    def __init__(self, stream):
        self.stream = stream

    def write(self, text):
        return self.stream.write(text)

    def writeln(self, text=''):
        self.stream.write(text + '\n')
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


class ChineseResult(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        self.started = time.perf_counter()
        self.before = (len(self.failures) + len(self.errors) + len(self.unexpectedSuccesses),
                       len(self.skipped), len(self.expectedFailures))

    def stopTest(self, test):
        failed = len(self.failures) + len(self.errors) + len(self.unexpectedSuccesses) > self.before[0]
        skipped = len(self.skipped) > self.before[1]
        expected = len(self.expectedFailures) > self.before[2]
        suffix = ' [跳过]' if skipped else ' [预期失败]' if expected else ''
        self.stream.writeln(row('✘' if failed else '﹣' if skipped else '✔',
                                time.perf_counter() - self.started, self.getDescription(test) + suffix))
        super().stopTest(test)

    def getDescription(self, test):
        original = getattr(test, 'test_case', test)
        name = getattr(original, '_testMethodName', '')
        description = (DESCRIPTIONS.get(type(original).__name__, {}).get(name)
                       or test.shortDescription() or str(test))
        # 失败的子用例保留参数, 便于定位具体的标签或校验值.
        parameters = getattr(test, 'params', None)
        if parameters:
            description += f' {dict(parameters)!r}'
        return description


def run_suite(suite, label):
    result = ChineseResult(ReportStream(sys.stdout), descriptions=True, verbosity=0)
    started = time.perf_counter()
    result.startTestRun()
    try:
        suite.run(result)
    finally:
        result.stopTestRun()
    # 保留 unittest 收集的完整失败详情, 自定义报告不改变测试退出状态.
    result.printErrors()
    summary = (f'{label}测试完成: 共 {result.testsRun} 项, '
               f'失败 {len(result.failures)} 项, 错误 {len(result.errors)} 项')
    for name, entries in [('跳过', result.skipped), ('预期失败', result.expectedFailures),
                          ('非预期通过', result.unexpectedSuccesses)]:
        if entries:
            summary += f', {name} {len(entries)} 项'
    result.stream.writeln(row('✔' if result.wasSuccessful() else '✘', time.perf_counter() - started, summary))
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description='以统一格式输出回归测试结果')
    parser.add_argument('--label', default='Python')
    commands = parser.add_subparsers(dest='mode', required=True)
    discovery = commands.add_parser('discover')
    discovery.add_argument('directory')
    discovery.add_argument('--pattern', default='test_*.py')
    file = commands.add_parser('file')
    file.add_argument('path')
    file.add_argument('arguments', nargs=argparse.REMAINDER)
    command = commands.add_parser('command')
    command.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.mode == 'command':
        if not args.arguments:
            parser.error('缺少要运行的命令')
        started = time.perf_counter()
        # 独立浏览器和 SDK 脚本沿用原入口, 成功时收起内部日志, 失败时完整输出.
        try:
            result = subprocess.run(args.arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except OSError as error:
            print(row('✘', time.perf_counter() - started, args.label), flush=True)
            print(str(error), flush=True)
            return 1
        print(row('✔' if result.returncode == 0 else '✘', time.perf_counter() - started, args.label), flush=True)
        if result.returncode != 0:
            print(result.stdout, end='', flush=True)
        return 0 if result.returncode == 0 else 1
    if args.mode == 'discover':
        suite = unittest.defaultTestLoader.discover(str(Path(args.directory).resolve()), pattern=args.pattern)
    else:
        path = Path(args.path).resolve()
        # 有些测试会在导入时读取二进制路径, 保持直接运行脚本时的参数与导入目录.
        sys.path.insert(0, str(path.parent))
        sys.argv = [str(path), *args.arguments]
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    return run_suite(suite, args.label)


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python

import argparse
import array
import copy
import functools
import imp
import os
import re
import psutil
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

class AccdFailedException(Exception):
  pass

class ModuleCoverage:
  def __init__(self, sancov_path):
    name_components = os.path.basename(sancov_path).split('.')
    num_components = len(name_components)
    if num_components != 2 and num_components != 3:
      raise AccdFailedException('Bad sancov filename at ' + sancov_path)
    self.module = name_components[0]
    self.pid = int(name_components[1]) if num_components == 3 else -1
    self.read_sancov(sancov_path)

  def merge(self, other):
    got_new_coverage = not other.offsets <= self.offsets
    self.offsets |= other.offsets
    return got_new_coverage

  def save(self, directory):
    sancov_path = os.path.join(directory, self.module + '.sancov')
    self.write_sancov(sancov_path)

  def read_sancov(self, sancov_path):
    f = open(sancov_path, mode="rb")
    size = os.fstat(f.fileno()).st_size
    self.offsets = set(array.array('I', f.read(size)))
    f.close()

  def write_sancov(self, sancov_path):
    f = open(sancov_path, mode="w+b")
    array.array('I', self.offsets).tofile(f)
    f.close()

class Coverage:
  def __init__(self, directory='', sancov_regex=''):
    self.modules = {}
    if directory:
      regex = re.compile(sancov_regex)
      for filename in os.listdir(directory):
        if regex.match(filename):
          sancov_path = os.path.join(directory, filename)
          self.merge_sancov_file(sancov_path)
      
  def merge_sancov_file(self, sancov_path):
    module = ModuleCoverage(sancov_path)
    return self.merge_module(module)

  def merge_module(self, module):
    module_name = module.module
    if module_name in self.modules:
      return self.modules[module_name].merge(module)
    else:
      self.modules[module_name] = copy.deepcopy(module)
      return len(module.offsets) != 0

  def merge(self, other):
    got_new_coverage = False
    for module in other.modules.values():
      got_new_coverage |= self.merge_module(module)
    return got_new_coverage

  def save(self, directory):
    for module in self.modules.values():
      module.save(directory)

class Accd:
  def __init__(self):
    self.devnull = open(os.devnull, "r+b")

  def parse_args(self):
    description        =  'Coverage tool based on ASAN coverage.'
    corpus_dir_help    = ('Directory where to store the distilled corpus. '
                          'If it already exists, newly distilled testcases will be added.')
    testcases_dir_help =  'Input directory with undistilled testcases.'
    command_help       = ('The rest of the command line will be executed as a command that '
                          'processes a testcase. The following can be referenced: '
                          '%%testcase - full path of a testcase, '
                          '%%work_dir - temporary working directory of the command. ')
    timeout_help       =  'Timeout in seconds for the command will be killed.'
    sancov_regex_help  = ('Regular expression that selects which of the generated .sancov files '
                          'should be used for coverage. %%pid matches the pid of command process. '
                          '%%pid is useful if the command executes child processes, whose .sancov '
                          'files should be ignored.')
    print_new_coverage_help = 'Print out function names of new coverage.'
    num_jobs_help      = ('Number of concurrent jobs that run testcases. The default is '
                          'psutil.NUM_CPUS.')
    hide_gui_help      =  'Redirect GUI to fake X server. Requires xvfb and icewm to be installed.'
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('corpus_dir', help=corpus_dir_help)
    parser.add_argument('testcases_dir', help=testcases_dir_help)
    parser.add_argument('command', help=command_help, nargs=argparse.REMAINDER)
    parser.add_argument('--timeout', type=float, dest='timeout', default=None, help=timeout_help)
    parser.add_argument('--sancov-regex', dest='sancov_regex', default='.*\.sancov',
                        help=sancov_regex_help)
    parser.add_argument('--print-new-coverage', dest='print_new_coverage', default=False,
                        action='store_true', help=print_new_coverage_help)
    parser.add_argument('--num-jobs', type=int, dest='num_jobs', default=psutil.NUM_CPUS, help=num_jobs_help)
    parser.add_argument('--hide-gui', dest='hide_gui', default=False, action='store_true',
                        help=hide_gui_help)
    self.parser = parser
    return parser.parse_args()

  def program_is_running(self, program):
    for process in psutil.process_iter():
      if process.name == program:
        return True
    return False

  def run_program(self, command, cwd=None, preexec_fn=None):
    devnull = self.devnull
    process = psutil.Popen(command, cwd=cwd, preexec_fn=preexec_fn,
                           stdin=devnull, stdout=devnull, stderr=devnull);
    return process

  def run_program_if_not_running(self, program):
    if not self.program_is_running(program[0]):
      self.run_program(program)

  def bring_up_fake_x(self):
    if self.args.hide_gui:
      os.environ['DISPLAY'] = ':10.0'
      self.run_program_if_not_running(['Xvfb', ':10.0'])
      self.run_program_if_not_running(['icewm'])

  def enable_coverage_dump(self):
    asan_options = os.environ.get('ASAN_OPTIONS', '')
    if asan_options:
      asan_options += ':'
    os.environ['ASAN_OPTIONS'] = asan_options + 'coverage=1'

  def read_total_coverage(self):
    self.corpus_dir = self.args.corpus_dir
    self.coverage_dir = os.path.join(self.corpus_dir, 'coverage')
    if not os.path.isdir(self.corpus_dir):
      os.mkdir(self.corpus_dir)
    if os.path.isdir(self.coverage_dir):
      self.total_coverage = Coverage(self.coverage_dir)
    else:
      self.total_coverage = Coverage()

  def busy_wait(self, timeout, finished):
    have_timeout = timeout is not None
    if have_timeout:
      endtime = time.time() + timeout
    delay = 0.0005
    while True:
      if finished():
        return False
      delay = min(delay * 2, .05)
      if have_timeout:
        remaining = endtime - time.time()
        if remaining <= 0:
          return True
        delay = min(delay, remaining)
      time.sleep(delay)

  def process_is_zombie(self, process):
    return process.status == psutil.STATUS_ZOMBIE

  def wait_process_group(self, leader, timeout):
    leader_is_dead = functools.partial(self.process_is_zombie, leader)
    if self.busy_wait(timeout, leader_is_dead):
      os.killpg(leader.pid, signal.SIGTERM)
      time.sleep(3)
    os.killpg(leader.pid, signal.SIGKILL)
    leader.wait()

  def get_testcase_coverage(self, testcase_path):
    work_dir = tempfile.mkdtemp()
    command = []
    for arg in self.args.command:
      arg = arg.replace('%testcase', testcase_path)
      arg = arg.replace('%work_dir', work_dir)
      command.append(arg)
    process = self.run_program(command, work_dir, os.setpgrp)
    self.wait_process_group(process, self.args.timeout)
    sancov_regex = self.args.sancov_regex.replace('%pid', str(process.pid))
    testcase_coverage = Coverage(work_dir, sancov_regex)
    shutil.rmtree(work_dir)
    return testcase_coverage

  def testcase_processor_thread(self, thread_id):
    while True:
      with self.testcases_lock:
        if not self.testcases:
          return
        filename = self.testcases.pop()
        self.testcase_index += 1
        testcase_index = self.testcase_index
      with self.print_lock:
        print ('[%d/%d] Processing %s by thread %d' %
               (testcase_index, self.testcase_count, filename, thread_id))
      testcase_path = os.path.join(self.testcases_dir, filename)
      testcase_coverage = self.get_testcase_coverage(testcase_path)
      with self.coverage_lock:
        got_new_coverage = self.total_coverage.merge(testcase_coverage)
      if got_new_coverage:
        testcase_save_path = os.path.join(self.corpus_dir, filename)
        shutil.copyfile(testcase_path, testcase_save_path)

  def process_testcases(self):
    testcases_dir = self.args.testcases_dir
    if not os.path.isdir(testcases_dir):
      raise AccdFailedException('Directory ' + testcases_dir + ' does not exist.')
    command = self.args.command[0]
    if command.startswith('.'):
      self.args.command[0] = os.path.abspath(command)
    self.testcases_dir = os.path.abspath(testcases_dir)
    self.testcases = os.listdir(self.testcases_dir)
    self.testcase_count = len(self.testcases)
    self.testcase_index = 0
    self.testcases_lock = threading.Lock()
    self.coverage_lock = threading.Lock()
    self.print_lock = threading.Lock()
    for i in xrange(self.args.num_jobs):
      thread = threading.Thread(target=self.testcase_processor_thread, args=(i, ))
      thread.setDaemon(True)
      thread.start()
    while threading.active_count() != 1:
      time.sleep(0.1)

  def save_total_coverage(self):
    if os.path.isdir(self.coverage_dir):
      shutil.rmtree(self.coverage_dir)
    os.mkdir(self.coverage_dir)
    self.total_coverage.save(self.coverage_dir)

  def run(self):
    self.args = self.parse_args()
    if not self.args.command:
      self.parser.print_help()
      return 1
    self.bring_up_fake_x()
    self.enable_coverage_dump()
    self.read_total_coverage()
    self.process_testcases()
    self.save_total_coverage()
    return 0

if __name__ == '__main__':
  accd = Accd()
  sys.exit(accd.run())

#===============================================================================
# Copyright 2012 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#===============================================================================

#============= enthought library imports =======================
from traits.api import Str, Any, Bool, Property, Int
from pyface.confirmation_dialog import confirm
#============= standard library imports ========================
import time
import os
import inspect
from threading import Event, Thread, Lock
import traceback
#============= local library imports  ==========================

from pychron.loggable import Loggable

from Queue import Empty, LifoQueue
# from pychron.globals import globalv
# from pychron.core.ui.gui import invoke_in_main_thread
import sys
# import bdb
# from pychron.core.ui.thread import Thread
import weakref
from pychron.globals import globalv
from pychron.wait.wait_control import WaitControl
from pychron.pyscripts.error import PyscriptError, IntervalError, GosubError, \
    KlassError, MainError


class IntervalContext(object):
    def __init__(self, obj, dur):
        self.obj = obj
        self.dur = dur

    def __enter__(self):
        self.obj.begin_interval(duration=self.dur)

    def __exit__(self, *args):
        self.obj.complete_interval()


def verbose_skip(func):
    def decorator(obj, *args, **kw):


        fname = func.__name__
        #        print fname, obj.testing_syntax, obj._cancel
        if fname.startswith('_m_'):
            fname = fname[3:]

        args1, _, _, defaults = inspect.getargspec(func)

        nd = sum([1 for di in defaults if di is not None]) if defaults else 0

        min_args = len(args1) - 1 - nd
        an = len(args) + len(kw)
        if an < min_args:
            raise PyscriptError('invalid arguments count for {}, args={} kwargs={}'.format(fname,
                                                                                           args, kw))
            #        if obj.testing_syntax or obj._cancel:
        #            return
        if obj.testing_syntax or obj._cancel or obj._truncate:
            return

        obj.debug('{} {} {}'.format(fname, args, kw))

        return func(obj, *args, **kw)

    return decorator


def skip(func):
    def decorator(obj, *args, **kw):
        if obj.testing_syntax or obj._cancel or obj._truncate:
            return
        return func(obj, *args, **kw)

    return decorator


def count_verbose_skip(func):
    def decorator(obj, *args, **kw):
        if obj._truncate or obj._cancel:
            return

        fname = func.__name__
        #        print fname, obj.testing_syntax, obj._cancel
        if fname.startswith('_m_'):
            fname = fname[3:]

        args1, _, _, defaults = inspect.getargspec(func)

        nd = sum([1 for di in defaults if di is not None]) if defaults else 0

        min_args = len(args1) - 1 - nd
        an = len(args) + len(kw)
        if an < min_args:
            raise PyscriptError('invalid arguments count for {}, args={} kwargs={}'.format(fname,
                                                                                           args, kw))
            #        if obj._cancel:
        if obj.testing_syntax:
        #             print func.func_name, obj._estimated_duration
            func(obj, calc_time=True, *args, **kw)
            #             print func.func_name, obj._estimated_duration
            return

        obj.debug('{} {} {}'.format(fname, args, kw))

        return func(obj, *args, **kw)

    return decorator


def makeRegistry():
    registry = {}

    def registrar(func):
        registry[func.__name__] = func.__name__
        return func  # normally a decorator returns a wrapped function,
        # but here we return func unmodified, after registering it

    registrar.commands = registry
    return registrar


def makeNamedRegistry(cmd_register):
    def named_register(name):
        def decorator(func):
            cmd_register.commands[name] = func.__name__
            return func

        return decorator

    return named_register


command_register = makeRegistry()
named_register = makeNamedRegistry(command_register)

'''
@todo: cancel script if action fails. eg fatal comm. error
'''


class PyScript(Loggable):
    text = Property
    syntax_checked = Property

    manager = Any
    #     parent = Any
    parent_script = Any

    root = Str
    filename = Str
    info_color = Str

    testing_syntax = Bool(False)
    cancel_flag = Bool
    hash_key = None

    _ctx = None
    _text = Str

    _interval_stack = None
    #     _interval_flag = None

    _cancel = Bool(False)
    _completed = False
    _truncate = False

    _syntax_checked = False
    _syntax_error = None
    _gosub_script = None
    _wait_control = None

    _estimated_duration = 0
    _graph_calc = False

    trace_line = Int

    def __init__(self, *args, **kw):
        super(PyScript, self).__init__(*args, **kw)
        self._block_lock = Lock()

    def calculate_estimated_duration(self):
        self._estimated_duration = 0
        if not self._syntax_checked:
            self.debug('calculate_estimated duration. syntax requires testing')
            self.test()
        # self._set_syntax_checked(False)
        # self.test()
        return self.get_estimated_duration()

    def traceit(self, frame, event, arg):
        if event == "line":
            co = frame.f_code
            if co.co_filename == self.filename:
                lineno = frame.f_lineno
                self.trace_line = lineno

        return self.traceit

    def execute(self, new_thread=False, bootstrap=True,
                trace=False,
                finished_callback=None, 
                argv=None):
        if bootstrap:
            self.bootstrap()

        if not self.syntax_checked:
            self.test()

        def _ex_():
            self._execute(trace, argv)
            if finished_callback:
                finished_callback()

            self.finished()
            return self._completed

        if new_thread:
            t = Thread(target=_ex_)
            t.start()
            #             self._t = t
            return t
        else:
            return _ex_()

            #     def execute(self, new_thread=False, bootstrap=True, finished_callback=None):
            #
            #         def _ex_():
            #             if bootstrap:
            #                 self.bootstrap()
            #
            #             ok = True
            #             if not self.syntax_checked:
            #                 self.test()
            #
            #             if ok:
            #                 self._execute()
            #                 if finished_callback:
            #                     finished_callback()
            #
            #             return self._completed
            #
            #         if new_thread:
            #             t = Thread(target=_ex_)
            #             t.start()
            #         else:
            #             return _ex_()

    def test(self, argv=None):
        if not self.syntax_checked:
            self.syntax_checked = True
            self.testing_syntax = True
            self._syntax_error = True

            r = self._execute(argv=argv)
            if r is not None:
                self.info('invalid syntax')
                ee = PyscriptError(self.filename, r)
                raise ee

            elif not self._interval_stack.empty():
                raise IntervalError()

            else:
                self.info('syntax checking passed')
                self._syntax_error = False

            self.testing_syntax = False

    def compile_snippet(self, snippet):
        try:
            code = compile(snippet, '<string>', 'exec')
        except Exception, e:
            return e
        else:
            return code

    def _tracer(self, frame, event, arg):
        if event == 'line':
            print frame.f_code.co_filename, frame.f_lineno

        return self._tracer

    def execute_snippet(self, trace=False, argv=None):
        safe_dict = self.get_context()

        if trace:
            snippet = self.filename
        else:
            snippet = self.text

        if trace:
            sys.settrace(self.traceit)
            import imp

            try:
                script = imp.load_source('script', snippet)
            except Exception, e:
                return e
            script.__dict__.update(safe_dict)
            try:
                script.main(*argv)
            except TypeError:
                script.main()
            except AttributeError:
                return MainError

        else:
        #         sys.settrace(self._tracer)
            code_or_err = self.compile_snippet(snippet)
            if not isinstance(code_or_err, Exception):
                try:
                    exec code_or_err in safe_dict
                    func=safe_dict['main']
                    if argv is None:
                        argv=tuple()
                    func(*argv)

                except KeyError, e:
                    return MainError()
                except Exception, e:
                    return traceback.format_exc(limit=5)
            else:
                return code_or_err

    def syntax_ok(self):
        try:
            self.test()
        except PyscriptError, e:
            self.warning_dialog(e)
            return False

        return True
        # return not self._syntax_error

    def check_for_modifications(self):
        old = self.toblob()
        with open(self.filename, 'r') as f:
            new = f.read()

        return old != new

    def toblob(self):
        return self.text

    def get_estimated_duration(self):
        return self._estimated_duration

    def set_default_context(self):
        pass

    def setup_context(self, **kw):
        if self._ctx is None:
            self._ctx = dict()

        self._ctx.update(kw)

    def get_context(self):
        ctx = dict()
        for k in self.get_commands():
            if isinstance(k, tuple):
                ka, kb = k
                name, func = ka, getattr(self, kb)
            else:
                name, func = k, getattr(self, k)

            ctx[name] = func

        for v in self.get_variables():
            ctx[v] = getattr(self, v)

        if self._ctx:
            ctx.update(self._ctx)
        return ctx

    def get_variables(self):
        return []

    #    def get_core_commands(self):
    #        cmds = [
    # #                ('info', '_m_info')
    #                ]
    #
    #        return cmds
    #    def get_script_commands(self):
    #        return []

    def get_commands(self):
    #        return self.get_core_commands() + \
    #        return self.get_script_commands() + \
        return self.get_command_register() + \
               command_register.commands.items()

    def get_command_register(self):
        return []

    def truncate(self, style=None):
        if style is None:
            self._truncate = True

        if self._gosub_script is not None:
            self._gosub_script.truncate(style=style)

    def cancel(self):
        self._cancel = True
        if self._gosub_script is not None:
            if not self._gosub_script._cancel:
                self._gosub_script.cancel()

                #         if self.parent:
                #             self.parent._executing = False

        if self.parent_script:
            if not self.parent_script._cancel:
                self.parent_script.cancel()

        if self._wait_control:
            self._wait_control.stop()

        self._cancel_hook()

    def bootstrap(self, load=True, **kw):
    #         self._interval_flag = Event()
    #         self._interval_stack = Queue()

        self._interval_stack = LifoQueue()

        if self.root and self.name and load:
            with open(self.filename, 'r') as f:
                self.text = f.read()

            return True

            #==============================================================================
            # commands
            #==============================================================================

    @command_register
    def gosub(self, name=None, root=None, klass=None, argv=None, **kw):
        if not name.endswith('.py'):
            name += '.py'

        if root is None:
            d = None
            if '/' in name:
                d = '/'
            elif ':' in name:
                d = ':'

            if d:
                dirs = name.split(d)
                name = dirs[0]
                for di in dirs[1:]:
                    name = os.path.join(name, di)

            root = self.root

        p = os.path.join(root, name)
        if not os.path.isfile(p):
            raise GosubError(p)

        if klass is None:
            klass = self.__class__
        else:
            klassname = klass
            pkg = 'pychron.pyscripts.api'
            mod = __import__(pkg, fromlist=[klass])
            klass = getattr(mod, klass)

        if not klass:
            raise KlassError(klassname)

        s = klass(root=root,
                  #                          path=p,
                  name=name,
                  manager=self.manager,
                  parent_script=weakref.ref(self)(),

                  _syntax_checked=self._syntax_checked,
                  _ctx=self._ctx,
                  **kw
        )

        if self.testing_syntax:
            s.bootstrap()
            err = s.test(argv=argv)
            if err:
                raise PyscriptError(self.name, err)

        else:
            if not self._cancel:
                self.info('doing GOSUB')
                self._gosub_script = s
                s.execute(argv=argv)
                self._gosub_script = None
                if not self._cancel:
                    self.info('gosub finished')

    @verbose_skip
    @command_register
    def exit(self):
        self.info('doing EXIT')
        self.cancel()

    @command_register
    def interval(self, dur):
        return IntervalContext(self, dur)

    @command_register
    def complete_interval(self):
        try:
            _, f, n = self._interval_stack.get(timeout=0.01)
        except Empty:
            raise IntervalError()

        if self.testing_syntax:
            return

        if self._cancel:
            return

        self.info('COMPLETE INTERVAL waiting for {} to complete'.format(n))
        # wait until flag is set
        while not f.isSet():
            if self._cancel:
                break
            self._sleep(0.5)

        if not self._cancel:
            f.clear()

    @command_register
    def begin_interval(self, duration=0, name=None):
        self._estimated_duration += duration

        if self._cancel:
            return

        def wait(dur, flag, n):
            self._sleep(dur)
            if not self._cancel:
                self.info('{} finished'.format(n))
                flag.set()

        duration = float(duration)

        t, f = None, None
        if name is None:
            name = 'Interval {}'.format(self._interval_stack.qsize() + 1)

        if not self.testing_syntax:
            f = Event()
            self.info('BEGIN INTERVAL {} waiting for {}'.format(name, duration))
            t = Thread(name=name,
                       target=wait, args=(duration, f, name))
            t.start()

        self._interval_stack.put((t, f, name))


    @command_register
    def sleep(self, duration=0, message=None):

        self._estimated_duration += duration
        if self.parent_script is not None:
            self.parent_script._estimated_duration += self._estimated_duration

        #         if self._graph_calc:
        #             va = self._xs[-1] + duration
        #             self._xs.append(va)
        #             self._ys.append(self._ys[-1])
        #             return

        if self.testing_syntax or self._cancel:
            return

        self.info('SLEEP {}'.format(duration))
        if globalv.experiment_debug:
        #             duration = 0.5
            self.debug('using debug sleep {}'.format(duration))

        self._sleep(duration, message=message)

    @skip
    @named_register('info')
    def _m_info(self, message=None):
        message = str(message)
        self.info(message)

        try:
            if self.manager:
                if self.info_color:
                    self.manager.info(message, color=self.info_color, log=False)
                else:
                    self.manager.info(message, log=False)

        except AttributeError, e:
            self.debug('m_info {}'.format(e))

    def finished(self):
    #         self._ctx = None
        self._finished()

    #===============================================================================
    # handlers
    #===============================================================================
    def _cancel_flag_changed(self, v):
        if v:
            result = confirm(None,
                             'Are you sure you want to cancel {}'.format(self.logger_name),
                             title='Cancel Script')
            #            result = confirmation(None, 'Are you sure you want to cancel {}'.format(self.logger_name))
            if result != 5104:
                self.cancel()
            else:
                self.cancel_flag = False
                #===============================================================================
                # private
                #===============================================================================

    def _execute(self, trace=False, argv=None):

        self._cancel = False
        self._completed = False
        self._truncate = False

        error = self.execute_snippet(trace, argv)
        if error:
            self.warning(str(error))
            return error

        if self.testing_syntax:
            return

        if self._cancel:
            self.info('{} canceled'.format(self.name))
        else:
            self.info('{} completed successfully'.format(self.name))
            self._completed = True
            #             if self.parent:
            #                 self.parent._executing = False
            #                 try:
            #                     del self.parent.scripts[self.hash_key]
            #                 except KeyError:
            #                     pass

    def _manager_action(self, func, name=None, protocol=None, *args, **kw):
        man = self.manager
        if protocol is not None and man is not None:
            app = man.application
        else:
            app = self.application

        if app is not None:
            args = (protocol,)
            if name is not None:
                args = (protocol, 'name=="{}"'.format(name))

            man = app.get_service(*args)

        if man is not None:
            if not isinstance(func, list):
                func = [(func, args, kw)]

            return [getattr(man, f)(*a, **k) for f, a, k in func]
        else:
            self.warning('could not find manager {}'.format(name))

    def _cancel_hook(self):
        pass

    def _finished(self):
        pass

    #==============================================================================
    # Sleep/ Wait
    #==============================================================================
    def _sleep(self, v, message=None):
        v = float(v)

        if v > 1:
            self._block(v, message=message, dialog=True)
        else:
            time.sleep(v)

    def _setup_wait_control(self, timeout, message):
        if self.manager:
            wd=self.manager.get_wait_control()
        else:
            wd = self._wait_control

        if wd is None:
            wd = WaitControl()

        self._wait_control = wd
        if self.manager:
            self.manager.wait_group.active_control = wd
        msg = 'Waiting for {:0.1f}  {}'.format(timeout, message)
        self.debug(msg)
        wd.trait_set(message=msg, wtime=timeout)
        wd.start(block=False, wtime=timeout)

        return wd

    def _block(self, timeout, message=None, dialog=False):
        self.debug('block started')
        st = time.time()
        if dialog:
            if message is None:
                message = ''

            """
                use lock to synchronize wait control creation
                this is necessary so that the created wait control has a chance to start
                before the next control asks if the active control is running.

            """
            with self._block_lock:
                wd = self._setup_wait_control(timeout, message)

            wd.join()

            if self.manager:
                self.manager.wait_group.pop(wd)

            if wd.is_canceled():
                self.cancel()
            elif wd.is_continued():
                self.info('continuing script after {:0.3f} s'.format(time.time() - st))

        else:
            while time.time() - st < timeout:
                if self._cancel:
                    break
                time.sleep(0.05)

        self.debug('block finished. duration {}'.format(time.time() - st))

        #===============================================================================

        # properties

    #===============================================================================
    @property
    def filename(self):
        return os.path.join(self.root, self.name)

    @property
    def state(self):
        # states
        # 0=running
        # 1=canceled
        # 2=completed
        if self._cancel:
            return '1'

        if self._completed:
            return '2'

        return '0'

    def _get_text(self):
        return self._text

    def _set_text(self, t):
        self._text = t

    def _get_syntax_checked(self):
        return self._syntax_checked

    def _set_syntax_checked(self, v):
        self._syntax_checked = v

    def __str__(self):
        return self.name


if __name__ == '__main__':
    class DummyManager(Loggable):
        def open_valve(self, *args, **kw):
            self.info('open valve')

        def close_valve(self, *args, **kw):
            self.info('close valve')

    from pychron.core.helpers.logger_setup import logging_setup

    logging_setup('pscript')
    #    execute_script(t)
    from pychron.paths import paths

    p = PyScript(root=os.path.join(paths.scripts_dir, 'pyscripts'),
                 path='test.py',
                 _manager=DummyManager())

    p.execute()
#============= EOF =============================================

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

path=Path(__file__).resolve().parents[1]/'scripts/lifecycle.py'
spec=importlib.util.spec_from_file_location('lifecycle',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def service(**changes):
    return dict({'service':'postgres','running':True,'health':'healthy','status':'running','exit_code':0,'oom_killed':False},**changes)


class LifecycleTests(unittest.TestCase):
    def test_all_healthy_required(self):
        self.assertEqual(module.state_errors([service()],{'postgres'},'running'),[])
        self.assertTrue(module.state_errors([service(health='unhealthy')],{'postgres'},'running'))

    def test_missing_and_duplicate_container(self):
        self.assertTrue(module.state_errors([],{'postgres'},'running'))
        self.assertTrue(module.state_errors([service(),service()],{'postgres'},'running'))

    def test_stop_rejects_running(self):
        self.assertTrue(module.state_errors([service()],{'postgres'},'stopped'))

    def test_forced_or_oom_exit_is_not_success(self):
        self.assertTrue(module.state_errors([service(running=False,status='exited',exit_code=137)],{'postgres'},'stopped'))
        self.assertTrue(module.state_errors([service(running=False,status='exited',oom_killed=True)],{'postgres'},'stopped'))

    def test_sigterm_and_never_created_are_stopped(self):
        self.assertEqual(module.state_errors([service(running=False,status='exited',exit_code=143)],{'postgres'},'stopped'),[])
        self.assertEqual(module.state_errors([],{'postgres'},'stopped'),[])

    @patch.object(module,'save_status')
    @patch.object(module,'event')
    @patch.object(module,'inspect_project',return_value=[])
    @patch.object(module,'command',side_effect=module.LifecycleError('command_timeout'))
    def test_timeout_records_failure(self,command,inspect,event,save):
        self.assertEqual(module.execute('start'),1)
        self.assertFalse(save.call_args.args[0]['verified'])
        self.assertEqual(save.call_args.args[0]['error'],'command_timeout')


if __name__=='__main__': unittest.main()

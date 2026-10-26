"""Synthetic tunnel supervisor policy; never invoke Docker or Internet."""
import importlib.util
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


class FakeOps:
    def __init__(self):
        self.local_ok=True
        self.internet_ok=True
        self.public='OK'
        self.started=1000
        self.url='https://qa-current.trycloudflare.com'
        self.status='running'
        self.restarts=0
        self.restart_error=False

    def local(self): return self.local_ok
    def network(self): return self.internet_ok
    def tunnel(self): return {'status':self.status,'started':self.started}
    def latest_url(self,started):
        assert started==self.started
        return self.url
    def probe(self,url):
        assert url==self.url
        return self.public
    def restart(self):
        self.restarts+=1
        if self.restart_error: raise RuntimeError('synthetic failure')
    def reserve(self,state):pass


class TunnelGuardTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('infrastructure.deployment.tunnel_guard'))
        from infrastructure.deployment import tunnel_guard
        self.guard=tunnel_guard
        self.ops=FakeOps()

    def cycle(self,state=None,now=2000,maintenance=False):
        return self.guard.cycle(state or {},self.ops,now=now,maintenance=maintenance)

    def test_healthy_does_not_restart_and_publishes_only_verified_current_url(self):
        result=self.cycle({'link':'https://old.trycloudflare.com/login'})
        self.assertEqual(result['status'],'HEALTHY')
        self.assertEqual(result['link'],self.ops.url+'/login')
        self.assertEqual(self.ops.restarts,0)

    def test_two_failures_restart_only_tunnel_then_next_probe_recovers(self):
        self.ops.public='FAILED'
        first=self.cycle()
        self.assertEqual(first['status'],'SUSPECT')
        second=self.cycle(first,2060)
        self.assertEqual(second['status'],'RESTARTED')
        self.assertIsNone(second['link'])
        self.assertEqual(self.ops.restarts,1)
        self.ops.public='OK';self.ops.started=2060
        self.assertEqual(self.cycle(second,2120)['status'],'HEALTHY')

    def test_app_network_auth_rate_or_maintenance_never_restart(self):
        for kind in ('app','network','AUTH_REQUIRED','THROTTLED','maintenance'):
            with self.subTest(kind=kind):
                self.ops=FakeOps();self.ops.public='FAILED'
                if kind=='app':self.ops.local_ok=False
                if kind=='network':self.ops.internet_ok=False
                if kind in ('AUTH_REQUIRED','THROTTLED'):self.ops.public=kind
                result=self.cycle({'failures':5},maintenance=kind=='maintenance')
                self.assertNotEqual(result['status'],'RESTARTED')
                self.assertIsNone(result['link'])
                self.assertEqual(self.ops.restarts,0)

    def test_startup_grace_and_external_restart_reset_failure_streak(self):
        self.ops.public='FAILED';self.ops.started=1990
        result=self.cycle({'failures':4,'generation':'old'})
        self.assertEqual(result['status'],'STARTING')
        self.assertEqual(self.ops.restarts,0)
        self.ops.started=1500
        result=self.cycle(result)
        self.assertEqual(result['status'],'SUSPECT')

    def test_cooldown_and_budget_prevent_restart_storm(self):
        self.ops.public='FAILED'
        result=self.cycle({'generation':'1000','failures':5,'last_restart':1900})
        self.assertEqual(result['status'],'COOLDOWN')
        result=self.cycle({'generation':'1000','failures':5,'restarts':[1700,1800,1900]})
        self.assertEqual(result['status'],'BUDGET_EXHAUSTED')
        self.assertEqual(self.ops.restarts,0)

    def test_restart_failure_reserves_cooldown_and_never_keeps_old_link(self):
        self.ops.public='FAILED';self.ops.restart_error=True
        result=self.cycle({'generation':'1000','failures':5,'link':'https://old.trycloudflare.com/login'})
        self.assertEqual(result['status'],'RESTART_FAILED')
        self.assertEqual(result['last_restart'],2000)
        self.assertIsNone(result['link'])
        self.assertEqual(self.cycle(result,2060)['status'],'COOLDOWN')

    def test_latest_log_url_and_restricted_commands(self):
        current='https://last.trycloudflare.com'
        self.assertEqual(self.guard.parse_url('https://first.trycloudflare.com\n'+current),current)
        self.assertIsNone(self.guard.parse_url('https://not-a-tunnel.example'))
        self.assertEqual(self.guard.TUNNEL,'triton-wms-home-tunnel-1')

    def test_log_rotation_can_recheck_same_generation_but_never_reuse_old_generation(self):
        self.ops.url=None
        self.ops.probe=lambda url:'OK' if url=='https://saved.trycloudflare.com' else 'FAILED'
        state={'generation':'1000','observed_url':'https://saved.trycloudflare.com'}
        self.assertEqual(self.cycle(state)['status'],'HEALTHY')
        self.assertEqual(self.cycle({**state,'generation':'old'})['status'],'SUSPECT')

    def test_restart_command_is_fixed_and_never_targets_application_or_host(self):
        ops=self.guard.Operations()
        with patch.object(ops,'command') as command:
            ops.restart()
            command.assert_called_once_with('restart','--timeout','15',self.guard.TUNNEL,timeout=30)

    def test_http_auth_redirect_and_limit_are_not_recovery_candidates(self):
        ops=self.guard.Operations()
        for code,wanted in ((302,'AUTH_REQUIRED'),(401,'AUTH_REQUIRED'),(403,'AUTH_REQUIRED'),(429,'THROTTLED'),(503,'FAILED')):
            with self.subTest(code=code),patch.object(ops,'read',side_effect=HTTPError('https://qa.trycloudflare.com',code,'qa',{},None)):
                self.assertEqual(ops.probe('https://qa.trycloudflare.com'),wanted)

    def test_epoch_generation_does_not_round_distinct_container_starts(self):
        self.ops.started=1792990001;self.ops.public='FAILED'
        previous={'generation':'1792990000','failures':5,'observed_url':'https://old.trycloudflare.com'}
        result=self.cycle(previous,1792990201)
        self.assertEqual(result['generation'],'1792990001')
        self.assertEqual(result['status'],'SUSPECT')
        self.assertEqual(self.ops.restarts,0)

    def test_failed_docker_check_withdraws_old_link_and_preserves_restart_budget(self):
        for operation in ('tunnel','latest_url'):
            with self.subTest(operation=operation),patch.object(self.ops,operation,side_effect=RuntimeError('QA unavailable')):
                result=self.cycle({'link':'https://old.trycloudflare.com/login','last_restart':1900,'restarts':[1900]})
                self.assertEqual(result['status'],'CHECK_FAILED')
                self.assertIsNone(result['link'])
                self.assertEqual(result['restarts'],[1900])
                self.assertEqual(self.ops.restarts,0)

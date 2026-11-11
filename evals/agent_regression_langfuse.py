"""Publish deterministic component regressions separately from live Agent tests."""
import json
import unittest
from pathlib import Path
from src.agent import env_utils
from src.agent.observability import client

GROUPS={
 'src.test.test_chat_interrupts':'审批SSE事件与中断状态',
 'src.test.test_observability':'遥测脱敏与故障隔离',
 'src.test.test_progressive_skills':'Skills渐进加载与路径边界',
 'src.test.test_sandbox_lifecycle':'沙箱生命周期与恢复逻辑',
 'src.test.test_memory_integration':'记忆集成与用户隔离',
 'src.test.test_business_eval':'业务验收判定器',
 'src.test.test_hybrid_review':'规则模型审查路由与执行信号',
 'src.test.test_jev_router':'模型路由异常与降级',
}

def main():
    cloud=client()
    if cloud is None or not cloud.auth_check():raise RuntimeError('Langfuse unavailable')
    rows=[]
    for module,title in GROUPS.items():
        root=cloud.start_observation(name='组件回归：'+title,as_type='span',
            metadata={'suite':'agent-component','scope':'unit/integration with test doubles; not real model/Docker/ERP'})
        result=unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromName(module).run(result)
        row={'group':title,'tests':result.testsRun,'failures':len(result.failures),
             'errors':len(result.errors),'skipped':len(result.skipped),'successful':result.wasSuccessful(),
             'trace_id':root.trace_id,'failed_tests':[t.id() for t,_ in result.failures+result.errors]}
        root.update(output=row)
        cloud.create_score(trace_id=root.trace_id,name='component_suite_pass',value=int(result.wasSuccessful()),data_type='BOOLEAN')
        root.end();rows.append(row)
    cloud.flush()
    output=Path('evals/business/results/agent-component-20261023.json')
    output.write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    print(json.dumps(rows,ensure_ascii=False),flush=True)

if __name__=='__main__':main()

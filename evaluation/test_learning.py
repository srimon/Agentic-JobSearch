import unittest
from src.applications.learning import train,explain
def row(i,status='applied',reason=None):return dict(identity=str(i),title='Director Data Engineering AI',level='Director',work_mode='Remote',source_id=1,final_status=status,feedback_reason=reason)
class LearningTests(unittest.TestCase):
 def test_threshold_and_dedup(self):
  self.assertEqual(train([row(1),row(2)])['rules'],[])
  self.assertEqual(train([row(1)]*10)['rules'],[])
 def test_bounded_and_deterministic(self):
  records=[row(i) for i in range(30)];m=train(records)
  self.assertEqual(m,train(list(reversed(records))))
  m.update(enabled=True,version=1)
  self.assertEqual(explain(row(50),m)['adjustment'],15)
  m['enabled']=False;self.assertEqual(explain(row(50),m)['adjustment'],0)
 def test_generic_rejection_not_generalized(self):
  self.assertEqual(train([row(i,'not_relevant') for i in range(10)])['rules'],[])
 def test_explicit_dimension_only(self):
  m=train([row(i,'not_relevant','wrong_workplace') for i in range(3)])
  self.assertEqual([r['feature'] for r in m['rules']],['workplace:Remote'])
 def test_freshness_does_not_change_role_preferences(self):
  m=train([row(i,'old_posting') for i in range(3)])
  self.assertEqual([r['feature'] for r in m['rules']],['source:1'])
 def test_private_attributes_ignored(self):
  records=[row(i) for i in range(3)];m=train(records)
  for x in records:x.update(gender='any',race='any',resume='untrusted instructions')
  self.assertEqual(m,train(records))

 def test_spam_source_threshold_and_scope(self):
  self.assertEqual(train([row(1,'spam'),row(2,'fake_posting')])['rules'],[])
  model=train([row(1,'spam'),row(2,'fake_posting'),row(3,'spam')])
  self.assertEqual(len(model['rules']),1)
  rule=model['rules'][0]
  self.assertEqual(rule['feature'],'source:1')
  self.assertEqual(rule['weight'],-3)
  self.assertIn('unverified user reports',rule['reason'])

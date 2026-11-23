import unittest
from research.researcher import validate_proposal, training_config

class ProposalTests(unittest.TestCase):
    def test_config_stays_in_finite_search_space(self):
        p=dict(architecture='mlp',depth=4,min_leaf=1,hidden_size=8,epochs=20,learning_rate=.03)
        config=training_config(p)
        self.assertEqual(config['max_candidates'],1)
        for key,value in [('architecture','shell'),('depth',100000),('min_leaf',True)]:
            bad=dict(p);bad[key]=value
            with self.assertRaises(ValueError):validate_proposal(bad)
        with self.assertRaises(ValueError):validate_proposal(dict(p,command='anything'))
        with self.assertRaises(ValueError):validate_proposal({})

if __name__=='__main__':unittest.main()

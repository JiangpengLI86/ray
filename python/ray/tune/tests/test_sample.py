"""
If you ever run into issues like
https://gist.github.com/xwjiang2010/13e6df091e5938aff5b44769bec8ffb8,
change your pytest running directory to ray/python/ray/tune/tests/
"""

import sys
import unittest
from collections import defaultdict
from unittest.mock import patch

import numpy as np
import pytest

import ray
import ray.tune.search.sample
from ray import tune
from ray.tune import Experiment
from ray.tune.search.util import logger
from ray.tune.search.variant_generator import generate_variants


def _mock_objective(config):
    tune.report(config)


def assertDictAlmostEqual(a, b):
    for k, v in a.items():
        assert k in b, f"Key {k} not found in {b}"
        w = b[k]

        assert type(v) is type(w), f"Type {type(v)} is not {type(w)}"

        if isinstance(v, dict):
            assert assertDictAlmostEqual(v, w), f"Subdict {v} != {w}"
        elif isinstance(v, (int, float)):
            assert np.isclose(v, w)
        elif isinstance(v, (list, tuple)):
            # Does not work for nested dicts or lists
            assert all(x == y for x, y in zip(v, w))
        else:
            assert v == w

    return True


class SearchSpaceTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "func": tune.sample_from(lambda spec: spec.config.uniform * 0.01),
            "uniform": tune.uniform(-5, -1),
            "quniform": tune.quniform(3.2, 5.4, 0.2),
            "loguniform": tune.loguniform(1e-4, 1e-2),
            "qloguniform": tune.qloguniform(1e-4, 1e-1, 5e-5),
            "choice": tune.choice([2, 3, 4]),
            "randint": tune.randint(-9, 15),
            "lograndint": tune.lograndint(1, 10),
            "qrandint": tune.qrandint(-21, 12, 3),
            "qrandint_q3": tune.qrandint(1, 10, 3),
            "qrandint_q1": tune.qrandint(1, 5, 1),
            "qlograndint": tune.qlograndint(2, 20, 2),
            "randn": tune.randn(10, 2),
            "qrandn": tune.qrandn(10, 2, 0.2),
        }

    def tearDown(self):
        ray.shutdown()

    def _testTuneSampleAPI(self, configs, ignore=None, check_stats=True):
        ignore = ignore or []
        stats = defaultdict(list)

        for out in configs:
            for k, v in out.items():
                if k not in ignore:
                    stats[k].append(v)

            if "func" not in ignore:
                self.assertAlmostEqual(out["func"], out["uniform"] * 0.01)

            if "uniform" not in ignore:
                self.assertGreaterEqual(out["uniform"], -5)
                self.assertLess(out["uniform"], -1)

            if "quniform" not in ignore:
                self.assertGreaterEqual(out["quniform"], 3.2)
                self.assertLessEqual(out["quniform"], 5.4)
                self.assertAlmostEqual(
                    out["quniform"] / 0.2, round(out["quniform"] / 0.2)
                )

            if "loguniform" not in ignore:
                self.assertGreaterEqual(out["loguniform"], 1e-4)
                self.assertLess(out["loguniform"], 1e-2)

            if "qloguniform" not in ignore:
                self.assertGreaterEqual(out["qloguniform"], 1e-4)
                self.assertLessEqual(out["qloguniform"], 1e-1)
                self.assertAlmostEqual(
                    out["qloguniform"] / 5e-5, round(out["qloguniform"] / 5e-5)
                )

            if "choice" not in ignore:
                self.assertIn(out["choice"], [2, 3, 4])

            if "randint" not in ignore:
                self.assertGreaterEqual(out["randint"], -9)
                self.assertLess(out["randint"], 15)
                self.assertTrue(isinstance(out["randint"], int))

            if "lograndint" not in ignore:
                self.assertGreaterEqual(out["lograndint"], 1)
                self.assertLess(out["lograndint"], 10)
                self.assertTrue(isinstance(out["lograndint"], int))

            if "qrandint" not in ignore:
                self.assertGreaterEqual(out["qrandint"], -21)
                self.assertLessEqual(out["qrandint"], 12)
                self.assertEqual(out["qrandint"] % 3, 0)
                self.assertTrue(isinstance(out["qrandint"], int))

            if "qrandint_q3" not in ignore:
                self.assertGreaterEqual(out["qrandint_q3"], 1)
                self.assertLessEqual(out["qrandint_q3"], 10)
                self.assertEqual(out["qrandint_q3"] % 3, 0)
                self.assertTrue(isinstance(out["qrandint_q3"], int))

            if "qrandint_q1" not in ignore:
                self.assertGreaterEqual(out["qrandint_q1"], 1)
                self.assertLessEqual(out["qrandint_q1"], 5)
                self.assertEqual(out["qrandint_q1"] % 1, 0)
                self.assertTrue(isinstance(out["qrandint_q1"], int))

            if "qlograndint" not in ignore:
                self.assertGreaterEqual(out["qlograndint"], 2)
                self.assertLessEqual(out["qlograndint"], 20)
                self.assertEqual(out["qlograndint"] % 2, 0)
                self.assertTrue(isinstance(out["qlograndint"], int))

            if "randn" not in ignore:
                # Very improbable
                self.assertGreater(out["randn"], 0)
                self.assertLess(out["randn"], 20)

            if "qrandn" not in ignore:
                self.assertGreater(out["qrandn"], 0)
                self.assertLess(out["qrandn"], 20)
                self.assertAlmostEqual(out["qrandn"] / 0.2, round(out["qrandn"] / 0.2))

        if check_stats:
            for k, v in stats.items():
                if k == "choice":
                    self.assertIn(2, v, msg="choice failed for 2")
                    self.assertIn(3, v, msg="choice failed for 3")
                    self.assertIn(4, v, msg="choice failed for 4")

                elif k == "randint":
                    for i in range(-9, 15):
                        self.assertIn(i, v, msg=f"randint failed for i={i}")

                elif k == "qrandint":
                    for i in range(-21, 13, 3):
                        self.assertIn(i, v, msg=f"qrandint failed for i={i}")

                elif k == "qrandint_q3":
                    for i in range(3, 11, 3):
                        self.assertIn(i, v, msg=f"qrandint_q3 failed for i={i}")

                elif k == "qrandint_q1":
                    for i in range(1, 5, 1):
                        self.assertIn(i, v, msg=f"qrandint_q1 failed for i={i}")

                elif k == "lograndint":
                    for i in range(1, 10):
                        self.assertIn(i, v, msg=f"lograndint failed for i={i}")

                elif k == "qlograndint":
                    for i in range(2, 21, 2):
                        self.assertIn(i, v, msg=f"qlograndint failed for i={i}")

    def testSampleBoundsRandom(self):
        config = self.config.copy()

        def config_generator():
            for i in range(1000):
                for _, generated in generate_variants({"config": config}):
                    yield generated["config"]

        self._testTuneSampleAPI(config_generator())

    def testReproducibility(self):
        config = self.config.copy()
        config.pop("func")

        def config_generator(random_state):
            if random_state is None:
                np.random.seed(1000)
            for _, generated in generate_variants(
                {"config": config},
                random_state=ray.tune.search.sample._BackwardsCompatibleNumpyRng(
                    random_state
                ),
            ):
                yield generated["config"]

        with patch("ray.tune.search.sample.LEGACY_RNG", True):
            global_seed_legacy = [
                next(config_generator(random_state=None)) for _ in range(100)
            ]
            seed_legacy = [
                next(config_generator(random_state=1000)) for _ in range(100)
            ]
            generator_legacy = [
                next(config_generator(random_state=np.random.RandomState(1000)))
                for _ in range(100)
            ]
            for i in range(100):
                assertDictAlmostEqual(global_seed_legacy[0], global_seed_legacy[i])
                assertDictAlmostEqual(global_seed_legacy[0], seed_legacy[i])
                assertDictAlmostEqual(global_seed_legacy[0], generator_legacy[i])

        if not ray.tune.search.sample.LEGACY_RNG:
            seed_new = [next(config_generator(random_state=1000)) for _ in range(100)]
            generator_new = [
                next(config_generator(random_state=np.random.default_rng(1000)))
                for _ in range(100)
            ]
            for i in range(100):
                assertDictAlmostEqual(seed_new[0], seed_new[i])
                assertDictAlmostEqual(seed_new[0], generator_new[i])

    def testReproducibilityBasicVariantGenerator(self):
        config = self.config.copy()
        config.pop("func")
        from ray.tune.search.basic_variant import BasicVariantGenerator

        ray.init(num_cpus=1, local_mode=True)

        num_samples = 5
        params = dict(
            run_or_experiment=_mock_objective,
            config=config,
            metric="uniform",
            mode="max",
            num_samples=num_samples,
        )
        with patch("ray.tune.search.sample.LEGACY_RNG", True):
            np.random.seed(1000)
            analysis_global_seed = tune.run(
                search_alg=BasicVariantGenerator(max_concurrent=1),  # global seed
                **params,
            )
            np.random.seed(1000)
            analysis_global_seed_2 = tune.run(
                search_alg=BasicVariantGenerator(max_concurrent=1),  # global seed
                **params,
            )
            analysis_seed = tune.run(
                search_alg=BasicVariantGenerator(max_concurrent=1, random_state=1000),
                **params,
            )
            analysis_seed_2 = tune.run(
                search_alg=BasicVariantGenerator(max_concurrent=1, random_state=1000),
                **params,
            )
            analysis_generator = tune.run(
                search_alg=BasicVariantGenerator(
                    max_concurrent=1, random_state=np.random.RandomState(1000)
                ),
                **params,
            )
            analysis_generator_2 = tune.run(
                search_alg=BasicVariantGenerator(
                    max_concurrent=1, random_state=np.random.RandomState(1000)
                ),
                **params,
            )
            for i in range(num_samples):
                assertDictAlmostEqual(
                    analysis_global_seed.trials[i].config,
                    analysis_seed.trials[i].config,
                )
                assertDictAlmostEqual(
                    analysis_global_seed.trials[i].config,
                    analysis_generator.trials[i].config,
                )
                assertDictAlmostEqual(
                    analysis_global_seed.trials[i].config,
                    analysis_global_seed_2.trials[i].config,
                )
                assertDictAlmostEqual(
                    analysis_global_seed.trials[i].config,
                    analysis_seed_2.trials[i].config,
                )
                assertDictAlmostEqual(
                    analysis_global_seed.trials[i].config,
                    analysis_generator_2.trials[i].config,
                )

        if not ray.tune.search.sample.LEGACY_RNG:
            analysis_seed = tune.run(
                search_alg=BasicVariantGenerator(max_concurrent=1, random_state=1000),
                **params,
            )
            analysis_seed_2 = tune.run(
                search_alg=BasicVariantGenerator(max_concurrent=1, random_state=1000),
                **params,
            )
            analysis_generator = tune.run(
                search_alg=BasicVariantGenerator(
                    max_concurrent=1, random_state=np.random.default_rng(1000)
                ),
                **params,
            )
            analysis_generator_2 = tune.run(
                search_alg=BasicVariantGenerator(
                    max_concurrent=1, random_state=np.random.default_rng(1000)
                ),
                **params,
            )
            for i in range(num_samples):
                assertDictAlmostEqual(
                    analysis_seed.trials[i].config, analysis_generator.trials[i].config
                )
                assertDictAlmostEqual(
                    analysis_seed.trials[i].config, analysis_seed_2.trials[i].config
                )
                assertDictAlmostEqual(
                    analysis_seed.trials[i].config,
                    analysis_generator_2.trials[i].config,
                )

    def testBoundedFloat(self):
        bounded = ray.tune.search.sample.Float(-4.2, 8.3)

        # Don't allow to specify more than one sampler
        with self.assertRaises(ValueError):
            bounded.normal().uniform()

        # Uniform
        samples = bounded.uniform().sample(size=1000)
        self.assertTrue(any(-4.2 < s < 8.3 for s in samples))
        self.assertFalse(np.mean(samples) < -2)

        # Loguniform
        with self.assertRaises(ValueError):
            bounded.loguniform().sample(size=1000)

        bounded_positive = ray.tune.search.sample.Float(1e-4, 1e-1)
        samples = bounded_positive.loguniform().sample(size=1000)
        self.assertTrue(any(1e-4 < s < 1e-1 for s in samples))

    def testUnboundedFloat(self):
        unbounded = ray.tune.search.sample.Float(None, None)

        # Require min and max bounds for loguniform
        with self.assertRaises(ValueError):
            unbounded.loguniform()

        # Normal
        samples = ray.tune.search.sample.Float(None, None).normal().sample(size=1000)
        self.assertTrue(any(-5 < s < 5 for s in samples))
        self.assertTrue(-1 < np.mean(samples) < 1)

    def testBoundedInt(self):
        bounded = ray.tune.search.sample.Integer(-3, 12)

        samples = bounded.uniform().sample(size=1000)
        self.assertTrue(any(-3 <= s < 12 for s in samples))
        self.assertFalse(np.mean(samples) < 2)

    def testCategorical(self):
        categories = [-2, -1, 0, 1, 2]
        cat = ray.tune.search.sample.Categorical(categories)

        samples = cat.uniform().sample(size=1000)
        self.assertTrue(any(-2 <= s <= 2 for s in samples))
        self.assertTrue(all(c in samples for c in categories))

    def testFunction(self):
        def sample(spec):
            return np.random.uniform(-4, 4)

        fnc = ray.tune.search.sample.Function(sample)

        samples = fnc.sample(size=1000)
        self.assertTrue(any(-4 < s < 4 for s in samples))
        self.assertTrue(-2 < np.mean(samples) < 2)

    def testFunctionSignature(self):
        from functools import partial

        def sample_a():
            return 0

        def sample_b(spec):
            return 1

        def sample_c(spec, b="ok"):
            return 2

        def sample_d_invalid(spec, b):
            return 3

        sample_d_valid = partial(sample_d_invalid, b="ok")

        for sample_fn in [sample_a, sample_b, sample_c, sample_d_valid]:
            fn = tune.sample_from(sample_fn)
            sample = fn.sample(None)
            self.assertIsNotNone(sample)

        with self.assertRaises(ValueError):
            fn = tune.sample_from(sample_d_invalid)
            print(fn.sample(None))

    def testQuantized(self):
        bounded_positive = ray.tune.search.sample.Float(1e-4, 1e-1)

        bounded = ray.tune.search.sample.Float(1e-4, 1e-1)
        with self.assertRaises(ValueError):
            # Granularity too high
            bounded.quantized(5e-4)

        with self.assertRaises(ValueError):
            ray.tune.search.sample.Float(-1e-1, -1e-4).quantized(5e-4)

        samples = bounded_positive.loguniform().quantized(5e-5).sample(size=1000)

        for sample in samples:
            factor = sample / 5e-5
            assert 1e-4 <= sample <= 1e-1
            self.assertAlmostEqual(factor, round(factor), places=10)

        with self.assertRaises(ValueError):
            ray.tune.search.sample.Float(0, 32).quantized(3)

        samples = ray.tune.search.sample.Float(0, 33).quantized(3).sample(size=1000)
        self.assertTrue(all(0 <= s <= 33 for s in samples))

    def testCategoricalDtype(self):
        dist = tune.choice([1.0, "str"])

        np.random.seed(1000)
        sample = dist.sample(size=100)
        self.assertTrue(
            all((x, type(x)) in [(1.0, float), ("str", str)] for x in sample)
        )

    def testCategoricalSeedInTrainingLoop(self):
        def train_fn(config):
            return 0

        config = {
            "integer": tune.randint(0, 100_000),
            "choice": tune.choice(list(range(100_000))),
        }

        np.random.seed(1000)

        out_1 = tune.run(train_fn, config=config, num_samples=8, verbose=0)

        integers_1 = [t.config["integer"] for t in out_1.trials]
        choices_1 = [t.config["choice"] for t in out_1.trials]

        np.random.seed(1000)

        out_2 = tune.run(train_fn, config=config, num_samples=8, verbose=0)

        integers_2 = [t.config["integer"] for t in out_2.trials]
        choices_2 = [t.config["choice"] for t in out_2.trials]

        self.assertSequenceEqual(integers_1, integers_2)
        self.assertSequenceEqual(choices_1, choices_2)

    def testConvertAx(self):
        from ax.service.ax_client import AxClient

        from ray.tune.search.ax import AxSearch

        # Grid search not supported, should raise ValueError
        with self.assertRaises(ValueError):
            AxSearch.convert_search_space({"grid": tune.grid_search([0, 1])})

        config = {
            "a": ray.tune.search.sample.Categorical([2, 3, 4]).uniform(),
            "b": {
                "x": ray.tune.search.sample.Integer(0, 5).quantized(2),
                "y": 4,
                "z": ray.tune.search.sample.Float(1e-4, 1e-2).loguniform(),
            },
        }
        converted_config = AxSearch.convert_search_space(config)
        ax_config = [
            {"name": "a", "type": "choice", "values": [2, 3, 4]},
            {"name": "b/x", "type": "range", "bounds": [0, 4], "value_type": "int"},
            {"name": "b/y", "type": "fixed", "value": 4},
            {
                "name": "b/z",
                "type": "range",
                "bounds": [1e-4, 1e-2],
                "value_type": "float",
                "log_scale": True,
            },
        ]

        client1 = AxClient(random_seed=1234)
        client1.create_experiment(
            parameters=converted_config, objective_name="a", minimize=False
        )
        searcher1 = AxSearch(ax_client=client1)

        client2 = AxClient(random_seed=1234)
        client2.create_experiment(
            parameters=ax_config, objective_name="a", minimize=False
        )
        searcher2 = AxSearch(ax_client=client2)

        config1 = searcher1.suggest("0")
        config2 = searcher2.suggest("0")

        self.assertEqual(config1, config2)
        self.assertIn(config1["a"], [2, 3, 4])
        self.assertIn(config1["b"]["x"], list(range(5)))
        self.assertEqual(config["b"]["y"], 4)
        self.assertLess(1e-4, config1["b"]["z"])
        self.assertLess(config1["b"]["z"], 1e-2)

        searcher = AxSearch(metric="a", mode="max")
        analysis = tune.run(
            _mock_objective, config=config, search_alg=searcher, num_samples=1
        )
        trial = analysis.trials[0]
        assert trial.config["a"] in [2, 3, 4]

        mixed_config = {"a": tune.uniform(5, 6), "b": tune.uniform(8, 9)}
        searcher = AxSearch(space=mixed_config, metric="a", mode="max")
        config = searcher.suggest("0")
        self.assertTrue(5 <= config["a"] <= 6)
        self.assertTrue(8 <= config["b"] <= 9)

    def testSampleBoundsAx(self):
        from ax import Models
        from ax.modelbridge.generation_strategy import (
            GenerationStep,
            GenerationStrategy,
        )
        from ax.service.ax_client import AxClient

        from ray.tune.search.ax import AxSearch

        ignore = [
            "func",
            "randn",
            "qrandn",
            "quniform",
            "qloguniform",
            "qrandint",
            "qrandint_q1",
            "qrandint_q3",
            "qlograndint",
        ]

        config = self.config.copy()
        for k in ignore:
            config.pop(k)

        # Legacy Ax versions (compatbile with Python 3.6)
        # use `num_arms` instead
        try:
            generation_strategy = GenerationStrategy(
                steps=[GenerationStep(model=Models.UNIFORM, num_arms=-1)]
            )
        except TypeError:
            generation_strategy = GenerationStrategy(
                steps=[GenerationStep(model=Models.UNIFORM, num_trials=-1)]
            )

        client1 = AxClient(
            enforce_sequential_optimization=False,
            generation_strategy=generation_strategy,
        )

        client1.create_experiment(
            parameters=AxSearch.convert_search_space(config),
            objective_name="a",
            minimize=False,
        )
        searcher1 = AxSearch(ax_client=client1)

        def config_generator():
            for i in range(50):
                yield searcher1.suggest(f"trial_{i}")

        # Unfortunately even random sampling in Ax takes a long time, so we
        # only sample 50 trials and don't do an extensive bounds check.
        # Full bounds check has been run locally and seems to work fine.
        self._testTuneSampleAPI(config_generator(), ignore=ignore, check_stats=False)

    def testConvertBayesOpt(self):
        from ray.tune.search.bayesopt import BayesOptSearch

        # Grid search not supported, should raise ValueError
        with self.assertRaises(ValueError):
            BayesOptSearch.convert_search_space({"grid": tune.grid_search([0, 1])})

        config = {
            "a": ray.tune.search.sample.Categorical([2, 3, 4]).uniform(),
            "b": {
                "x": ray.tune.search.sample.Integer(0, 5).quantized(2),
                "y": 4,
                "z": ray.tune.search.sample.Float(1e-4, 1e-2).loguniform(),
            },
        }
        with self.assertRaises(ValueError):
            converted_config = BayesOptSearch.convert_search_space(config)

        config = {"b": {"z": ray.tune.search.sample.Float(1e-4, 1e-2).loguniform()}}
        bayesopt_config = {"b/z": (1e-4, 1e-2)}
        converted_config = BayesOptSearch.convert_search_space(config)

        searcher1 = BayesOptSearch(space=converted_config, metric="none", mode="max")
        searcher2 = BayesOptSearch(space=bayesopt_config, metric="none", mode="max")

        config1 = searcher1.suggest("0")
        config2 = searcher2.suggest("0")

        self.assertEqual(config1, config2)
        self.assertLess(1e-4, config1["b"]["z"])
        self.assertLess(config1["b"]["z"], 1e-2)

        searcher = BayesOptSearch()

        invalid_config = {"a/b": tune.uniform(4.0, 8.0)}

        with self.assertRaises(ValueError):
            searcher.set_search_properties("none", "max", invalid_config)

        invalid_config = {"a": {"b/c": tune.uniform(4.0, 8.0)}}

        with self.assertRaises(ValueError):
            searcher.set_search_properties("none", "max", invalid_config)

        searcher = BayesOptSearch(metric="b/z", mode="max")
        analysis = tune.run(
            _mock_objective, config=config, search_alg=searcher, num_samples=1
        )
        trial = analysis.trials[0]
        self.assertLess(trial.config["b"]["z"], 1e-2)

        mixed_config = {"a": tune.uniform(5, 6), "b": (8.0, 9.0)}
        searcher = BayesOptSearch(space=mixed_config, metric="a", mode="max")
        config = searcher.suggest("0")
        self.assertTrue(5 <= config["a"] <= 6)
        self.assertTrue(8 <= config["b"] <= 9)

    def testSampleBoundsBayesOpt(self):
        from ray.tune.search.bayesopt import BayesOptSearch

        ignore = [
            "func",
            "choice",
            "randint",
            "lograndint",
            "randn",
            "qrandn",
            "quniform",
            "qloguniform",
            "qrandint",
            "qrandint_q1",
            "qrandint_q3",
            "qlograndint",
        ]

        config = self.config.copy()
        for k in ignore:
            config.pop(k)

        searcher = BayesOptSearch(
            space=config,
            metric="a",
            mode="max",
            skip_duplicate=False,
            random_search_steps=1000,
        )

        def config_generator():
            for i in range(1000):
                yield searcher.suggest(f"trial_{i}")

        self._testTuneSampleAPI(config_generator(), ignore=ignore)

    @pytest.mark.skipif(
        sys.version_info >= (3, 12),
        reason="BOHB not yet supported for python 3.12+",
    )
    def testConvertBOHB(self):
        import ConfigSpace

        from ray.tune.search.bohb import TuneBOHB

        # Grid search not supported, should raise ValueError
        with self.assertRaises(ValueError):
            TuneBOHB.convert_search_space({"grid": tune.grid_search([0, 1])})

        config = {
            "a": ray.tune.search.sample.Categorical([2, 3, 4]).uniform(),
            "b": {
                "x": ray.tune.search.sample.Integer(0, 5).quantized(2),
                "y": 4,
                "z": ray.tune.search.sample.Float(1e-4, 1e-2).loguniform(),
            },
        }
        converted_config = TuneBOHB.convert_search_space(config)
        bohb_config = ConfigSpace.ConfigurationSpace()
        bohb_config.add_hyperparameters(
            [
                ConfigSpace.CategoricalHyperparameter("a", [2, 3, 4]),
                ConfigSpace.UniformIntegerHyperparameter("b/x", lower=0, upper=4, q=2),
                ConfigSpace.UniformFloatHyperparameter(
                    "b/z", lower=1e-4, upper=1e-2, log=True
                ),
            ]
        )

        converted_config.seed(1234)
        bohb_config.seed(1234)

        searcher1 = TuneBOHB(space=converted_config, metric="a", mode="max")
        searcher2 = TuneBOHB(space=bohb_config, metric="a", mode="max")

        config1 = searcher1.suggest("0")
        config2 = searcher2.suggest("0")

        self.assertEqual(config1, config2)
        self.assertIn(config1["a"], [2, 3, 4])
        self.assertIn(config1["b"]["x"], list(range(5)))
        self.assertLess(1e-4, config1["b"]["z"])
        self.assertLess(config1["b"]["z"], 1e-2)

        searcher = TuneBOHB(metric="a", mode="max")
        analysis = tune.run(
            _mock_objective, config=config, search_alg=searcher, num_samples=1
        )
        trial = analysis.trials[0]
        self.assertIn(trial.config["a"], [2, 3, 4])
        self.assertEqual(trial.config["b"]["y"], 4)

        mixed_config = {
            "a": tune.uniform(5, 6),
            "b": tune.uniform(8, 9),  # Cannot mix ConfigSpace and Dict
        }
        searcher = TuneBOHB(space=mixed_config, metric="a", mode="max")
        config = searcher.suggest("0")
        self.assertTrue(5 <= config["a"] <= 6)
        self.assertTrue(8 <= config["b"] <= 9)

    @pytest.mark.skipif(
        sys.version_info >= (3, 12), reason="BOHB doesn't support py312"
    )
    def testSampleBoundsBOHB(self):
        from ray.tune.search.bohb import TuneBOHB

        ignore = [
            "func",
            "qloguniform",  # There seems to be an issue here
        ]

        config = self.config.copy()
        for k in ignore:
            config.pop(k)

        searcher = TuneBOHB(space=config, metric="a", mode="max")

        def config_generator():
            for i in range(1000):
                yield searcher.suggest(f"trial_{i}")

        self._testTuneSampleAPI(config_generator(), ignore=ignore)

    @pytest.mark.skipif(
        sys.version_info >= (3, 12), reason="HEBO doesn't support py312"
    )
    def testConvertHEBO(self):
        import torch
        from hebo.design_space.design_space import DesignSpace

        from ray.tune.search.hebo import HEBOSearch

        # Grid search not supported, should raise ValueError
        with self.assertRaises(ValueError):
            HEBOSearch.convert_search_space({"grid": tune.grid_search([0, 1])})

        config = {
            "a": ray.tune.search.sample.Categorical([2, 3, 4]).uniform(),
            "b": {
                "x": ray.tune.search.sample.Integer(0, 5),
                "y": 4,
                "z": ray.tune.search.sample.Float(1e-4, 1e-2).loguniform(),
            },
        }
        converted_config = HEBOSearch.convert_search_space(config)
        hebo_space_config = [
            {"name": "a", "type": "cat", "categories": [2, 3, 4]},
            {"name": "b/x", "type": "int", "lb": 0, "ub": 5},
            {"name": "b/z", "type": "pow", "lb": 1e-4, "ub": 1e-2},
        ]
        hebo_space = DesignSpace().parse(hebo_space_config)

        searcher1 = HEBOSearch(
            space=converted_config, metric="a", mode="max", random_state_seed=123
        )
        searcher2 = HEBOSearch(
            space=hebo_space, metric="a", mode="max", random_state_seed=123
        )

        np.random.seed(1234)
        torch.manual_seed(1234)
        config1 = searcher1.suggest("0")
        np.random.seed(1234)
        torch.manual_seed(1234)
        config2 = searcher2.suggest("0")

        self.assertEqual(config1, config2)
        self.assertIn(config1["a"], [2, 3, 4])
        self.assertIn(config1["b"]["x"], list(range(5)))
        self.assertLessEqual(1e-4, config1["b"]["z"])
        self.assertLessEqual(config1["b"]["z"], 1e-2)

        searcher = HEBOSearch(metric="a", mode="max", random_state_seed=123)
        analysis = tune.run(
            _mock_objective, config=config, search_alg=searcher, num_samples=1
        )
        trial = analysis.trials[0]
        self.assertIn(trial.config["a"], [2, 3, 4])
        self.assertEqual(trial.config["b"]["y"], 4)

        # Mixed configs are not supported

    @pytest.mark.skipif(
        sys.version_info >= (3, 12), reason="HEBO doesn't support py312"
    )
    def testSampleBoundsHEBO(self):
        from ray.tune.search.hebo import HEBOSearch

        ignore = [
            "func",
            "randn",
            "qrandn",
            "quniform",
            "qloguniform",
            "qrandint",
            "qrandint_q1",
            "qrandint_q3",
            "qlograndint",
        ]

        config = self.config.copy()
        for k in ignore:
            config.pop(k)

        searcher = HEBOSearch(space=config, metric="a", mode="max", max_concurrent=1000)

        def config_generator():
            for i in range(1000):
                yield searcher.suggest(f"trial_{i}")

        self._testTuneSampleAPI(config_generator(), ignore=ignore)

    def testConvertHyperOpt(self):
        from hyperopt import hp

        from ray.tune.search.hyperopt import HyperOptSearch

        # Grid search not supported, should raise ValueError
        with self.assertRaises(ValueError):
            HyperOptSearch.convert_search_space({"grid": tune.grid_search([0, 1])})

        config = {
            "a": ray.tune.search.sample.Categorical([2, 3, 4]).uniform(),
            "b": {
                "x": ray.tune.search.sample.Integer(-15, -10),
                "y": 4,
                "z": ray.tune.search.sample.Float(1e-4, 1e-2).loguniform(),
            },
        }
        converted_config = HyperOptSearch.convert_search_space(config)
        hyperopt_config = {
            "a": hp.choice("a", [2, 3, 4]),
            "b": {
                "x": hp.uniformint("x", -15, -11),
                "y": 4,
                "z": hp.loguniform("z", np.log(1e-4), np.log(1e-2)),
            },
        }

        searcher1 = HyperOptSearch(
            space=converted_config, random_state_seed=1234, metric="a", mode="max"
        )
        searcher2 = HyperOptSearch(
            space=hyperopt_config, random_state_seed=1234, metric="a", mode="max"
        )

        config1 = searcher1.suggest("0")
        config2 = searcher2.suggest("0")

        self.assertEqual(config1, config2)
        self.assertIn(config1["a"], [2, 3, 4])
        self.assertIn(config1["b"]["x"], list(range(-15, -10)))
        self.assertEqual(config1["b"]["y"], 4)
        self.assertLess(1e-4, config1["b"]["z"])
        self.assertLess(config1["b"]["z"], 1e-2)

        searcher = HyperOptSearch(metric="a", mode="max")
        analysis = tune.run(
            _mock_objective, config=config, search_alg=searcher, num_samples=1
        )
        trial = analysis.trials[0]
        assert trial.config["a"] in [2, 3, 4]

        mixed_config = {"a": tune.uniform(5, 6), "b": hp.uniform("b", 8, 9)}
        searcher = HyperOptSearch(space=mixed_config, metric="a", mode="max")
        config = searcher.suggest("0")
        self.assertTrue(5 <= config["a"] <= 6)
        self.assertTrue(8 <= config["b"] <= 9)

    def testConvertHyperOptChooseFromListOfList(self):
        from hyperopt import hp

        from ray.tune.search.hyperopt import HyperOptSearch

        config = {
            "a": tune.choice([[1, 2], [3, 4]]),
        }
        converted_config = HyperOptSearch.convert_search_space(config)
        hyperopt_config = {
            "a": hp.choice("a", [[1, 2], [3, 4]]),
        }

        searcher1 = HyperOptSearch(
            space=converted_config, random_state_seed=1234, metric="a", mode="max"
        )
        searcher2 = HyperOptSearch(
            space=hyperopt_config, random_state_seed=1234, metric="a", mode="max"
        )

        config1 = searcher1.suggest("0")
        config2 = searcher2.suggest("0")

        self.assertEqual(config1, config2)

        # Hyperopt natively converts list to tuple.
        # Try out the following script:
        # ```
        # a = HyperOptSearch.convert_search_space({"a": tune.choice([[1,2], [3,4]])})
        # print(hyperopt.pyll.stochastic.sample(a))
        # ```
        self.assertTrue(config1.get("a") in [(1, 2), (3, 4)])

    def testConvertHyperOptNested(self):
        from ray.tune.search.hyperopt import HyperOptSearch

        config = {
            "a": 1,
            "dict_nested": ray.tune.search.sample.Categorical(
                [
                    {
                        "a": ray.tune.search.sample.Categorical(["M", "N"]),
                        "b": ray.tune.search.sample.Categorical(["O", "P"]),
                    }
                ]
            ).uniform(),
            "list_nested": ray.tune.search.sample.Categorical(
                [
                    [
                        ray.tune.search.sample.Categorical(["M", "N"]),
                        ray.tune.search.sample.Categorical(["O", "P"]),
                    ],
                    [
                        ray.tune.search.sample.Categorical(["Q", "R"]),
                        ray.tune.search.sample.Categorical(["S", "T"]),
                    ],
                ]
            ).uniform(),
            "domain_nested": ray.tune.search.sample.Categorical(
                [
                    ray.tune.search.sample.Categorical(["M", "N"]),
                    ray.tune.search.sample.Categorical(["O", "P"]),
                ]
            ).uniform(),
        }

        searcher = HyperOptSearch(metric="a", mode="max")
        analysis = tune.run(
            _mock_objective,
            config=config,
            search_alg=searcher,
            num_samples=10,
        )

        for trial in analysis.trials:
            config = trial.config

            self.assertIn(config["dict_nested"]["a"], ["M", "N"])
            self.assertIn(config["dict_nested"]["b"], ["O", "P"])

            if config["list_nested"][0] in ["M", "N"]:
                self.assertIn(config["list_nested"][1], ["O", "P"])
            else:
                self.assertIn(config["list_nested"][0], ["Q", "R"])
                self.assertIn(config["list_nested"][1], ["S", "T"])

            self.assertIn(config["domain_nested"], ["M", "N", "O", "P"])

    def testConvertHyperOptConstant(self):
        from ray.tune.search.hyperopt import HyperOptSearch

        config = {"a": 4}

        searcher = HyperOptSearch()
        with self.assertRaisesRegex(
            RuntimeError, "This issue can also come up with HyperOpt"
        ):
            searcher.set_search_properties(metric="a", mode="max", config=config)

    def testSampleBoundsHyperopt(self):
        from ray.tune.search.hyperopt import HyperOptSearch

        # Todo: Hyperopt actually suffers from the same problem as we did before
        # https://github.com/ray-project/ray/pull/28187
        ignore = [
            "func",
            "qrandint_q3",
        ]

        config = self.config.copy()
        for k in ignore:
            config.pop(k)

        searcher = HyperOptSearch(
            space=config, metric="a", mode="max", n_initial_points=1000
        )

        def config_generator():
            for i in range(1000):
                yield searcher.suggest(f"trial_{i}")

        self._testTuneSampleAPI(config_generator(), ignore=ignore)

    def testConvertNevergrad(self):
        import nevergrad as ng

        from ray.tune.search.nevergrad import NevergradSearch

        # Grid search not supported, should raise ValueError
        with self.assertRaises(ValueError):
            NevergradSearch.convert_search_space({"grid": tune.grid_search([0, 1])})

        config = {
            "a": ray.tune.search.sample.Categorical([2, 3, 4]).uniform(),
            "b": {
                "x": ray.tune.search.sample.Integer(0, 5).quantized(2),
                "y": 4,
                "z": ray.tune.search.sample.Float(1e-4, 1e-2).loguniform(),
            },
        }
        converted_config = NevergradSearch.convert_search_space(config)
        nevergrad_config = ng.p.Dict(
            a=ng.p.Choice([2, 3, 4]),
            b=ng.p.Dict(
                x=ng.p.Scalar(lower=0, upper=5).set_integer_casting(),
                z=ng.p.Log(lower=1e-4, upper=1e-2),
            ),
        )

        searcher1 = NevergradSearch(
            optimizer=ng.optimizers.OnePlusOne,
            space=converted_config,
            metric="a",
            mode="max",
        )
        searcher2 = NevergradSearch(
            optimizer=ng.optimizers.OnePlusOne,
            space=nevergrad_config,
            metric="a",
            mode="max",
        )

        np.random.seed(1234)
        config1 = searcher1.suggest("0")
        np.random.seed(1234)
        config2 = searcher2.suggest("0")

        assertDictAlmostEqual(config1, config2)
        self.assertIn(config1["a"], [2, 3, 4])
        self.assertIn(config1["b"]["x"], list(range(5)))
        self.assertLess(1e-4, config1["b"]["z"])
        self.assertLess(config1["b"]["z"], 1e-2)

        searcher = NevergradSearch(
            optimizer=ng.optimizers.OnePlusOne, metric="a", mode="max"
        )
        analysis = tune.run(
            _mock_objective, config=config, search_alg=searcher, num_samples=1
        )
        trial = analysis.trials[0]
        assert trial.config["a"] in [2, 3, 4]

        mixed_config = {
            "a": tune.uniform(5, 6),
            "b": tune.uniform(8, 9),  # Cannot mix Nevergrad cfg and tune
        }
        searcher = NevergradSearch(
            space=mixed_config,
            optimizer=ng.optimizers.OnePlusOne,
            metric="a",
            mode="max",
        )
        config = searcher.suggest("0")
        self.assertTrue(5 <= config["a"] <= 6)
        self.assertTrue(8 <= config["b"] <= 9)

    def testSampleBoundsNevergrad(self):
        import nevergrad as ng

        from ray.tune.search.nevergrad import NevergradSearch

        ignore = [
            "func",
            "randn",
            "qrandn",
            "quniform",
            "qloguniform",
            "qrandint",
            "qrandint_q1",
            "qrandint_q3",
            "qlograndint",
        ]

        config = self.config.copy()
        for k in ignore:
            config.pop(k)

        optimizer = ng.optimizers.RandomSearchMaker(sampler="parametrization")

        searcher = NevergradSearch(
            space=config, metric="a", mode="max", optimizer=optimizer
        )

        def config_generator():
            for i in range(1000):
                yield searcher.suggest(f"trial_{i}")

        self._testTuneSampleAPI(config_generator(), ignore=ignore)

    def testConvertOptuna(self):
        import optuna
        from optuna.samplers import RandomSampler

        from ray.tune.search.optuna import OptunaSearch

        # Grid search not supported, should raise ValueError
        with self.assertRaises(ValueError):
            OptunaSearch.convert_search_space({"grid": tune.grid_search([0, 1])})

        config = {
            "a": ray.tune.search.sample.Categorical([2, 3, 4]).uniform(),
            "b": {
                "x": ray.tune.search.sample.Integer(0, 5).quantized(2),
                "y": 4,
                "z": ray.tune.search.sample.Float(1e-4, 1e-2).loguniform(),
            },
        }
        converted_config = OptunaSearch.convert_search_space(config)
        optuna_config = {
            "a": optuna.distributions.CategoricalDistribution([2, 3, 4]),
            "b": {
                "x": optuna.distributions.IntDistribution(0, 5, step=2),
                "z": optuna.distributions.FloatDistribution(1e-4, 1e-2, log=True),
            },
        }

        def optuna_define_by_run(ot_trial):
            ot_trial.suggest_categorical("a", [2, 3, 4])
            ot_trial.suggest_int("b/x", 0, 5, 2)
            ot_trial.suggest_loguniform("b/z", 1e-4, 1e-2)

        def optuna_define_by_run_with_constants(ot_trial):
            ot_trial.suggest_categorical("a", [2, 3, 4])
            ot_trial.suggest_int("b/x", 0, 5, 2)
            ot_trial.suggest_loguniform("b/z", 1e-4, 1e-2)
            return {"constant": 1}

        def optuna_define_by_run_invalid(ot_trial):
            ot_trial.suggest_categorical("a", [2, 3, 4])
            ot_trial.suggest_int("b/x", 0, 5, 2)
            ot_trial.suggest_loguniform("b/z", 1e-4, 1e-2)
            return 1

        sampler1 = RandomSampler(seed=1234)
        searcher1 = OptunaSearch(
            space=converted_config, sampler=sampler1, metric="a", mode="max"
        )

        sampler2 = RandomSampler(seed=1234)
        searcher2 = OptunaSearch(
            space=optuna_config, sampler=sampler2, metric="a", mode="max"
        )

        sampler3 = RandomSampler(seed=1234)
        searcher3 = OptunaSearch(
            space=optuna_define_by_run, sampler=sampler3, metric="a", mode="max"
        )

        sampler4 = RandomSampler(seed=1234)
        searcher4 = OptunaSearch(
            space=optuna_define_by_run_with_constants,
            sampler=sampler4,
            metric="a",
            mode="max",
        )

        config_constant = searcher4.suggest("0")
        self.assertIn("constant", config_constant)
        config_constant.pop("constant")

        sampler5 = RandomSampler(seed=1234)
        searcher5 = OptunaSearch(
            space=optuna_define_by_run_invalid, sampler=sampler5, metric="a", mode="max"
        )

        with self.assertRaises(TypeError):
            searcher5.suggest("0")

        config1 = searcher1.suggest("0")
        config2 = searcher2.suggest("0")
        config3 = searcher3.suggest("0")

        self.assertEqual(config1, config2)
        self.assertEqual(config1, config3)
        self.assertEqual(config1, config_constant)
        self.assertIn(config1["a"], [2, 3, 4])
        self.assertIn(config1["b"]["x"], list(range(5)))
        self.assertLess(1e-4, config1["b"]["z"])
        self.assertLess(config1["b"]["z"], 1e-2)

        def optuna_define_by_run_branching_invalid(ot_trial):
            # this is invalid because such a dict cannot be
            # unflattened (will try to assign child dicts to value under "a",
            # but that will be an int, instead of a dict)
            a = ot_trial.suggest_categorical("a", [1, 2])
            if a == 1:
                ot_trial.suggest_int("a/b", 0, 3)
                ot_trial.suggest_int("a/first", 2, 8)
            else:
                ot_trial.suggest_int("a/b", 4, 10)
                ot_trial.suggest_uniform("a/second", -0.4, 0.4)

        def optuna_define_by_run_branching(ot_trial):
            a = ot_trial.suggest_categorical("a", ["1", "2"])
            if a == "1":
                ot_trial.suggest_int("nest/b", 0, 3)
                ot_trial.suggest_int("nest/first", 2, 8)
            else:
                ot_trial.suggest_int("nest/b", 4, 10)
                ot_trial.suggest_uniform("nest/second", -0.4, 0.4)

        class MockOptunaSampler(RandomSampler):
            def __init__(self, seed) -> None:
                super().__init__(seed=seed)
                self.counter = 0

            def sample_independent(self, study, trial, param_name, param_distribution):
                if param_name == "a":
                    if self.counter == 0:
                        self.counter += 1
                        return param_distribution.choices[0]
                    return param_distribution.choices[1]
                return super().sample_independent(
                    study, trial, param_name, param_distribution
                )

        sampler_branching = RandomSampler(seed=1234)
        searcher_branching = OptunaSearch(
            space=optuna_define_by_run_branching_invalid,
            sampler=sampler_branching,
            metric="a",
            mode="max",
        )

        with self.assertRaises(TypeError):
            searcher_branching.suggest("0")

        sampler_branching = MockOptunaSampler(seed=1234)
        searcher_branching = OptunaSearch(
            space=optuna_define_by_run_branching,
            sampler=sampler_branching,
            metric="a",
            mode="max",
        )

        config_branching_1 = searcher_branching.suggest("0")
        self.assertIn("a", config_branching_1)
        self.assertEqual(config_branching_1["a"], "1")
        self.assertIn("nest", config_branching_1)
        self.assertIn("b", config_branching_1["nest"])
        self.assertIn("first", config_branching_1["nest"])
        self.assertGreater(4, config_branching_1["nest"]["b"])
        self.assertLess(0.5, config_branching_1["nest"]["first"])

        config_branching_2 = searcher_branching.suggest("1")
        self.assertIn("a", config_branching_2)
        self.assertEqual(config_branching_2["a"], "2")
        self.assertIn("nest", config_branching_2)
        self.assertIn("b", config_branching_2["nest"])
        self.assertIn("second", config_branching_2["nest"])
        self.assertLess(3, config_branching_2["nest"]["b"])
        self.assertGreater(0.5, config_branching_2["nest"]["second"])

        searcher = OptunaSearch(metric="a", mode="max")
        analysis = tune.run(
            _mock_objective, config=config, search_alg=searcher, num_samples=1
        )
        trial = analysis.trials[0]
        assert trial.config["a"] in [2, 3, 4]

        mixed_config = {
            "a": tune.uniform(5, 6),
            "b": tune.uniform(8, 9),  # Cannot mix List and Dict
        }
        searcher = OptunaSearch(space=mixed_config, metric="a", mode="max")
        config = searcher.suggest("0")
        self.assertTrue(5 <= config["a"] <= 6)
        self.assertTrue(8 <= config["b"] <= 9)

    def testSampleBoundsOptuna(self):
        from ray.tune.search.optuna import OptunaSearch

        # Quantization and log does not seem to work with Optuna
        # Also, qrandint works differently in Optuna (it moves the boundaries)
        ignore = [
            "func",
            "randn",
            "qrandn",
            "qloguniform",
            "qlograndint",
            "qrandint_q3",
        ]

        config = self.config.copy()
        for k in ignore:
            config.pop(k)

        searcher = OptunaSearch(space=config, metric="a", mode="max")

        def config_generator():
            for i in range(1000):
                yield searcher.suggest(f"trial_{i}")

        self._testTuneSampleAPI(config_generator(), ignore=ignore)

    def testConvertZOOpt(self):
        from zoopt import ValueType

        from ray.tune.search.zoopt import ZOOptSearch

        # Grid search not supported, should raise ValueError
        with self.assertRaises(ValueError):
            ZOOptSearch.convert_search_space({"grid": tune.grid_search([0, 1])})

        config = {
            "a": ray.tune.search.sample.Categorical([2, 3, 4]).uniform(),
            "b": {
                "x": ray.tune.search.sample.Integer(0, 5).quantized(2),
                "y": ray.tune.search.sample.Categorical([2, 4, 6, 8]).uniform(),
                "z": ray.tune.search.sample.Float(1e-4, 1e-2).loguniform(),
            },
        }
        # Does not support categorical variables
        with self.assertRaises(ValueError):
            converted_config = ZOOptSearch.convert_search_space(config)
        config = {
            "a": 2,
            "b": {
                "x": ray.tune.search.sample.Integer(0, 5).uniform(),
                "y": ray.tune.search.sample.Categorical([2, 4, 6, 8]).uniform(),
                "z": ray.tune.search.sample.Float(-3, 7).uniform().quantized(1e-4),
            },
        }
        converted_config = ZOOptSearch.convert_search_space(config)

        zoopt_config = {
            "b/x": (ValueType.DISCRETE, [0, 5], True),
            "b/y": (ValueType.GRID, [2, 4, 6, 8]),
            "b/z": (ValueType.CONTINUOUS, [-3, 7], 1e-4),
        }

        zoopt_search_config = {"parallel_num": 4}

        searcher1 = ZOOptSearch(
            dim_dict=converted_config,
            budget=5,
            metric="a",
            mode="max",
            **zoopt_search_config,
        )
        searcher2 = ZOOptSearch(
            dim_dict=zoopt_config,
            budget=5,
            metric="a",
            mode="max",
            **zoopt_search_config,
        )

        np.random.seed(1234)
        config1 = searcher1.suggest("0")
        np.random.seed(1234)
        config2 = searcher2.suggest("0")

        self.assertEqual(config1, config2)
        self.assertIn(config1["b"]["x"], list(range(5)))
        self.assertIn(config1["b"]["y"], [2, 4, 6, 8])
        self.assertLess(-3, config1["b"]["z"])
        self.assertLess(config1["b"]["z"], 7)

        searcher = ZOOptSearch(budget=5, metric="a", mode="max", **zoopt_search_config)
        analysis = tune.run(
            _mock_objective, config=config, search_alg=searcher, num_samples=1
        )
        trial = analysis.trials[0]
        self.assertIn(trial.config["b"]["y"], [2, 4, 6, 8])

        mixed_config = {
            "a": tune.uniform(5, 6),
            "b": (ValueType.CONTINUOUS, [8, 9], 1e-4),
        }
        searcher = ZOOptSearch(
            dim_dict=mixed_config,
            budget=5,
            metric="a",
            mode="max",
            **zoopt_search_config,
        )
        config = searcher.suggest("0")
        self.assertTrue(5 <= config["a"] <= 6)
        self.assertTrue(8 <= config["b"] <= 9)

    def testSampleBoundsZOOpt(self):
        self.skipTest(
            "ZOOpt parallel_num setting does not seem to be working, "
            "so skipping sampling test for now."
        )

        from ray.tune.search.zoopt import ZOOptSearch

        ignore = [
            "func",
            "randn",
            "qrandn",
            "qloguniform",
            "qlograndint",
            "quniform",
            "qrandint",
            "qrandint_q1",
            "qrandint_q3",
            "loguniform",
            "lograndint",
        ]

        config = self.config.copy()
        for k in ignore:
            config.pop(k)

        searcher = ZOOptSearch(budget=1000, parallel_num=1000)
        searcher.set_search_properties(metric="a", mode="max", config=config)

        def config_generator():
            for i in range(1000):
                yield searcher.suggest(f"trial_{i}")
                searcher.on_trial_complete(
                    f"trial_{i}", result=dict(a=np.random.uniform(size=1))
                )

        self._testTuneSampleAPI(config_generator(), ignore=ignore)

    def _testPointsToEvaluate(self, cls, config, exact=True, **kwargs):
        points_to_evaluate = [
            {k: v.sample() for k, v in config.items()} for _ in range(2)
        ]
        print(f"Points to evaluate: {points_to_evaluate}")
        searcher = cls(points_to_evaluate=points_to_evaluate, **kwargs)

        analysis = tune.run(
            _mock_objective,
            config=config,
            metric="metric",
            mode="max",
            search_alg=searcher,
            num_samples=5,
        )

        for i in range(len(points_to_evaluate)):
            trial_config = analysis.trials[i].config
            trial_config_dict = {
                "metric": trial_config["metric"],
                "a": trial_config["a"],
                "b": trial_config["b"],
                "c": trial_config["c"],
            }
            if not exact:
                for k, v in trial_config_dict.items():
                    self.assertAlmostEqual(v, points_to_evaluate[i][k], places=10)
            else:
                self.assertDictEqual(trial_config_dict, points_to_evaluate[i])

    def testPointsToEvaluateAx(self):
        config = {
            "metric": ray.tune.search.sample.Categorical([1, 2, 3, 4]).uniform(),
            "a": ray.tune.search.sample.Categorical(["t1", "t2", "t3", "t4"]).uniform(),
            "b": ray.tune.search.sample.Integer(0, 5),
            "c": ray.tune.search.sample.Float(1e-4, 1e-1).loguniform(),
        }

        from ray.tune.search.ax import AxSearch

        return self._testPointsToEvaluate(AxSearch, config)

    def testPointsToEvaluateBayesOpt(self):
        config = {
            "metric": ray.tune.search.sample.Float(10, 20).uniform(),
            "a": ray.tune.search.sample.Float(-30, -20).uniform(),
            "b": ray.tune.search.sample.Float(0, 5),
            "c": ray.tune.search.sample.Float(1e-4, 1e-1).loguniform(),
        }

        from ray.tune.search.bayesopt import BayesOptSearch

        return self._testPointsToEvaluate(BayesOptSearch, config)

    @pytest.mark.skipif(
        sys.version_info >= (3, 12), reason="BOHB not yet supported for python 3.12+"
    )
    def testPointsToEvaluateBOHB(self):
        config = {
            "metric": ray.tune.search.sample.Categorical([1, 2, 3, 4]).uniform(),
            "a": ray.tune.search.sample.Categorical(["t1", "t2", "t3", "t4"]).uniform(),
            "b": ray.tune.search.sample.Integer(0, 5),
            "c": ray.tune.search.sample.Float(1e-4, 1e-1).loguniform(),
        }

        from ray.tune.search.bohb import TuneBOHB

        return self._testPointsToEvaluate(TuneBOHB, config)

    def testPointsToEvaluateHyperOpt(self):
        config = {
            "metric": ray.tune.search.sample.Categorical([1, 2, 3, 4]).uniform(),
            "a": ray.tune.search.sample.Categorical(["t1", "t2", "t3", "t4"]).uniform(),
            "b": ray.tune.search.sample.Integer(0, 5),
            "c": ray.tune.search.sample.Float(1e-4, 1e-1).loguniform(),
        }

        from ray.tune.search.hyperopt import HyperOptSearch

        # See if we catch hyperopt errors caused by points to evaluate missing
        # keys found in space
        points_to_evaluate_missing_one = [
            {k: v.sample() for k, v in list(config.items())[:-1]}
        ]
        print(f"Points to evaluate: {points_to_evaluate_missing_one}")
        searcher = HyperOptSearch(points_to_evaluate=points_to_evaluate_missing_one)

        with self.assertRaises(ValueError):
            tune.run(
                _mock_objective,
                config=config,
                metric="metric",
                mode="max",
                search_alg=searcher,
                num_samples=5,
            )

        return self._testPointsToEvaluate(HyperOptSearch, config)

    def testPointsToEvaluateHyperOptNested(self):
        space = {
            "nested": [
                ray.tune.search.sample.Integer(0, 10),
                ray.tune.search.sample.Integer(0, 10),
            ],
            "nosample": [4, 8],
        }

        points_to_evaluate = [{"nested": [2, 4], "nosample": [4, 8]}]

        from ray.tune.search.hyperopt import HyperOptSearch

        searcher = HyperOptSearch(
            space=space, metric="_", mode="max", points_to_evaluate=points_to_evaluate
        )
        config = searcher.suggest(trial_id="0")

        self.assertSequenceEqual(config["nested"], points_to_evaluate[0]["nested"])

        self.assertSequenceEqual(config["nosample"], points_to_evaluate[0]["nosample"])

    def testPointsToEvaluateNevergrad(self):
        config = {
            "metric": ray.tune.search.sample.Categorical([1, 2, 3, 4]).uniform(),
            "a": ray.tune.search.sample.Categorical(["t1", "t2", "t3", "t4"]).uniform(),
            "b": ray.tune.search.sample.Integer(0, 5),
            "c": ray.tune.search.sample.Float(1e-4, 1e-1).loguniform(),
        }

        import nevergrad as ng

        from ray.tune.search.nevergrad import NevergradSearch

        return self._testPointsToEvaluate(
            NevergradSearch, config, exact=False, optimizer=ng.optimizers.OnePlusOne
        )

    def testPointsToEvaluateOptuna(self):
        config = {
            "metric": ray.tune.search.sample.Categorical([1, 2, 3, 4]).uniform(),
            "a": ray.tune.search.sample.Categorical(["t1", "t2", "t3", "t4"]).uniform(),
            "b": ray.tune.search.sample.Integer(0, 5),
            "c": ray.tune.search.sample.Float(1e-4, 1e-1).loguniform(),
        }

        from ray.tune.search.optuna import OptunaSearch

        return self._testPointsToEvaluate(OptunaSearch, config)

    def testPointsToEvaluateZoOpt(self):
        self.skipTest(
            "ZOOpt's latest release (0.4.1) does not support sampling "
            "initial points. Please re-enable this test after the next "
            "release."
        )

        config = {
            "metric": ray.tune.search.sample.Categorical([1, 2, 3, 4]).uniform(),
            "a": ray.tune.search.sample.Categorical(["t1", "t2", "t3", "t4"]).uniform(),
            "b": ray.tune.search.sample.Integer(0, 5),
            "c": ray.tune.search.sample.Float(1e-4, 1e-1).uniform(),
        }

        from ray.tune.search.zoopt import ZOOptSearch

        return self._testPointsToEvaluate(
            ZOOptSearch, config, budget=10, parallel_num=8
        )

    def testPointsToEvaluateBasicVariant(self):
        config = {
            "metric": ray.tune.search.sample.Categorical([1, 2, 3, 4]).uniform(),
            "a": ray.tune.search.sample.Categorical(["t1", "t2", "t3", "t4"]).uniform(),
            "b": ray.tune.search.sample.Integer(0, 5),
            "c": ray.tune.search.sample.Float(1e-4, 1e-1).loguniform(),
        }

        from ray.tune.search.basic_variant import BasicVariantGenerator

        return self._testPointsToEvaluate(BasicVariantGenerator, config)

    def testPointsToEvaluateBasicVariantAdvanced(self):
        config = {
            "grid_1": tune.grid_search(["a", "b", "c", "d"]),
            "grid_2": tune.grid_search(["x", "y", "z"]),
            "nested": {
                "random": tune.uniform(2.0, 10.0),
                "dependent": tune.sample_from(
                    lambda spec: -1.0 * spec.config.nested.random
                ),
            },
        }

        points = [
            {"grid_1": "b"},
            {"grid_2": "z"},
            {"grid_1": "a", "grid_2": "y"},
            {"nested": {"random": 8.0}},
        ]

        from ray.tune.search.basic_variant import BasicVariantGenerator

        # grid_1 * grid_2 are 3 * 4 = 12 variants per complete grid search
        # However if one grid var is set by preset variables, that run
        # is excluded from grid search.
        # Point 1 overwrites grid_1, so the first trial only grid searches
        # over grid_2 (3 trials).
        # The remaining 5 trials search over the whole space (5 * 12 trials)
        searcher = BasicVariantGenerator(points_to_evaluate=[points[0]])
        exp = Experiment(run=_mock_objective, name="test", config=config, num_samples=6)
        searcher.add_configurations(exp)
        self.assertEqual(searcher.total_samples, 1 * 3 + 5 * 12)

        # Point 2 overwrites grid_2, so the first trial only grid searches
        # over grid_1 (4 trials).
        # The remaining 5 trials search over the whole space (5 * 12 trials)
        searcher = BasicVariantGenerator(points_to_evaluate=[points[1]])
        exp = Experiment(run=_mock_objective, name="test", config=config, num_samples=6)
        searcher.add_configurations(exp)
        self.assertEqual(searcher.total_samples, 1 * 4 + 5 * 12)

        # Point 3 overwrites grid_1 and grid_2, so the first trial does not
        # grid search.
        # The remaining 5 trials search over the whole space (5 * 12 trials)
        searcher = BasicVariantGenerator(points_to_evaluate=[points[2]])
        exp = Experiment(run=_mock_objective, name="test", config=config, num_samples=6)
        searcher.add_configurations(exp)
        self.assertEqual(searcher.total_samples, 1 + 5 * 12)

        # When initialized with all points, the first three trials are
        # defined by the logic above. Only 3 trials are grid searched
        # compeletely.
        searcher = BasicVariantGenerator(points_to_evaluate=points)
        exp = Experiment(run=_mock_objective, name="test", config=config, num_samples=6)
        searcher.add_configurations(exp)
        self.assertEqual(searcher.total_samples, 1 * 3 + 1 * 4 + 1 + 3 * 12)

        # Run this and confirm results
        analysis = tune.run(exp, search_alg=searcher)
        configs = [trial.config for trial in analysis.trials]

        self.assertEqual(len(configs), searcher.total_samples)
        self.assertTrue(all(config["grid_1"] == "b" for config in configs[0:3]))
        self.assertTrue(all(config["grid_2"] == "z" for config in configs[3:7]))
        self.assertTrue(configs[7]["grid_1"] == "a" and configs[7]["grid_2"] == "y")
        self.assertTrue(configs[8]["nested"]["random"] == 8.0)
        self.assertTrue(configs[8]["nested"]["dependent"] == -8.0)

    def testPointsToEvaluateBasicVariantFixedParam(self):
        config = {
            "a": 1,
            "b": tune.randint(0, 3),
        }

        from ray.tune.search.basic_variant import BasicVariantGenerator
        from ray.tune.search.variant_generator import logger

        # Test whether the initial points of fixed parameters are correctly
        # verified.
        searcher = BasicVariantGenerator(
            points_to_evaluate=[
                {"a": 1, "b": 2},
            ]
        )
        analysis = tune.run(
            _mock_objective,
            name="test",
            config=config,
            search_alg=searcher,
            num_samples=2,
        )
        configs = [trial.config for trial in analysis.trials]

        self.assertEqual(searcher.total_samples, 2)
        self.assertEqual(len(configs), searcher.total_samples)
        self.assertEqual([cfg["a"] for cfg in configs], [1] * 2)
        self.assertEqual(configs[0]["b"], 2)

        # Test whether correctly throwing warning if the pre-set value of fixed
        # parameters isn't the same as its initial points
        searcher = BasicVariantGenerator(
            points_to_evaluate=[
                {"a": 2, "b": 2},
            ]
        )

        with patch.object(logger, "warning") as log_warning_mock:
            tune.run(
                _mock_objective,
                name="test",
                config=config,
                search_alg=searcher,
                num_samples=2,
            )
            log_warning_mock.assert_called_once()
            self.assertEqual(
                log_warning_mock.call_args[0],
                ("Pre-set value `2` is not equal to the value of parameter `a`: 1",),
            )

    def testGridSearchGenerator(self):
        from ray.tune.search.basic_variant import BasicVariantGenerator

        searcher = BasicVariantGenerator(constant_grid_search=False)
        exp = Experiment(
            run=_mock_objective,
            name="test",
            config={"parameter": tune.grid_search(range(10))},
            num_samples=1,
        )
        searcher.add_configurations(exp)

        trials = [searcher.next_trial() for i in range(10)]
        assert [t.config["parameter"] for t in trials] == list(range(10))

    def testConstantGridSearchBasicVariant(self):
        config = {
            "grid": tune.grid_search([1, 2, 3]),
            "rand": tune.uniform(0, 1000),
            "dependent_rand": tune.sample_from(lambda spec: spec.config.rand / 10),
            "dependent_grid": tune.sample_from(lambda spec: spec.config.grid / 10),
        }

        num_samples = 6

        from ray.tune.search.basic_variant import BasicVariantGenerator

        # First, do not keep random variables constant
        searcher = BasicVariantGenerator(constant_grid_search=False)
        exp = Experiment(
            run=_mock_objective, name="test", config=config, num_samples=num_samples
        )
        searcher.add_configurations(exp)

        configs = []
        while not searcher.is_finished():
            trial = searcher.next_trial()
            if not trial:
                break
            configs.append(trial.config)

        for i in range(num_samples):
            sub_configs = configs[i * 3 : i * 3 + 3]
            # These should not be equal, because we sample randomly for
            # each grid search value
            self.assertNotEqual(sub_configs[0]["rand"], sub_configs[1]["rand"])
            self.assertNotEqual(sub_configs[0]["rand"], sub_configs[2]["rand"])

        # Second, keep random variables constant
        searcher = BasicVariantGenerator(constant_grid_search=True)
        exp = Experiment(
            run=_mock_objective, name="test", config=config, num_samples=num_samples
        )
        searcher.add_configurations(exp)

        configs = []
        while not searcher.is_finished():
            trial = searcher.next_trial()
            if not trial:
                break
            configs.append(trial.config)

        for i in range(num_samples):
            sub_configs = configs[i * 3 : i * 3 + 3]
            # These should be equal, because we sample randomly first and
            # then keep the random values constant
            self.assertEqual(sub_configs[0]["rand"], sub_configs[1]["rand"])
            self.assertEqual(sub_configs[0]["rand"], sub_configs[2]["rand"])

        # Also, for different samples the random variables should differ
        self.assertEqual(configs[0]["grid"], configs[3]["grid"])
        self.assertNotEqual(configs[0]["rand"], configs[3]["rand"])

    @patch.object(logger, "warning")
    @pytest.mark.skipif(
        sys.version_info >= (3, 12),
        reason="TODO(justinvyu): not working for python 3.12 yet",
    )
    def testSetSearchPropertiesBackwardsCompatibility(self, mocked_warning_method):
        from ray.tune.search import Searcher

        class MySearcher(Searcher):
            def __init__(self, metric="a", mode="min", **kwargs):
                super(MySearcher, self).__init__(metric=metric, mode=mode, **kwargs)

            def suggest(self, trial_id):
                return {}

            def on_trial_complete(self, trial_id, result, **kwargs):
                pass

            # impl that has not been updated yet.
            def set_search_properties(self, metric, mode, config):
                pass

        tune.run(_mock_objective, config={"a": 1}, search_alg=MySearcher())
        mocked_warning_method.assert_called_once_with(
            "Please update custom Searcher to take in function signature "
            "as ``def set_search_properties(metric, mode, config, "
            "**spec) -> bool``."
        )


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__] + sys.argv[1:]))

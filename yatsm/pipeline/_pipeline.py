""" Classes representing pipeline objects
"""
import logging

from toolz import curry

from ._exec import delay_pipeline
from ._topology import config_to_tasks
from .language import CONFIG, OUTPUT, PIPE, REQUIRE, TASK
from .tasks import PIPELINE_TASKS, SEGMENT_TASKS

logger = logging.getLogger(__name__)


class Task(object):

    def __init__(self, func, require, output, **config):
        self.func = func
        self.funcname = self.func.__name__
        if self.func in SEGMENT_TASKS.items():
            self.create_group = True
        else:
            self.create_group = False
        self.require = require
        self.output = output
        self.config = config

    @classmethod
    def from_config(cls, config):
        task = config[TASK]
        try:
            func = PIPELINE_TASKS[task]
        except KeyError as ke:
            raise KeyError("Unknown pipeline task '{}'".format(task))
        return cls(func, config[REQUIRE], config[OUTPUT],
                   **config.get(CONFIG, {}))

    def curry(self):
        return curry(self.func, **self.spec)

    @property
    def is_eager(self):
        return getattr(self.func, 'is_eager', False)

# SHORTCUT GETTERS
    @property
    def spec(self):
        return {
            REQUIRE: self.require,
            OUTPUT: self.output,
            TASK: self.config
        }

    @property
    def require_data(self):
        return self.require.get('data', [])

    @property
    def require_record(self):
        return self.require.get('record', [])

    @property
    def output_data(self):
        return self.output.get('data', [])

    @property
    def output_record(self):
        return self.output.get('record', [])

    def __repr__(self):
        return ("<{0.__class__.__name__}: {0.func}( {0.require} )-> "
                "{0.output} >"
                .format(self))


class Pipeline(object):
    """
    """
    def __init__(self, tasks, config):
        self.tasks = tasks
        self.config = config
        self.eager_pipeline, self.pipeline = self._split_eager(self.tasks)

    @classmethod
    def from_config(cls, config, pipe, overwrite=True):
        """ Initialize a pipeline from a configuration and some data

        Args:
            config (dict): Pipeline configuration
            pipe (dict): "record" and "data" datasets
            overwrite (bool): Overwrite pre-existing results

        Returns:
            Pipeline: Pipeline of tasks
        """
        # Get sorted order based on config and input data
        task_names = config_to_tasks(config, pipe, overwrite=overwrite)
        tasks = [Task.from_config(config[name]) for name in task_names]

        return cls(tasks, config)

    def run_eager(self, pipe):
        pipeline = delay_pipeline(self.eager_pipeline, pipe)
        return pipeline.compute()

    def run(self, pipe, check_eager=True):
        # Check if pipe contains "eager" pipeline outputs
        if check_eager and not self._check_eager(self.eager_pipeline, pipe):
            logger.warning('Triggering eager compute')
            pipe = self.run_eager(pipe)
        pipeline = delay_pipeline(self.pipeline, pipe)
        return pipeline.compute()

    @staticmethod
    def _check_eager(tasks, pipe):
        """ Check if it looks like eager task results have been computed
        """
        for eager_task in tasks:
            data, rec = eager_task.output_data, eager_task.output_record
            has_rec = [output in pipe['record'] for output in rec]
            has_data = [output in pipe['data'] for output in data]
            if not all(has_data) and all(has_rec):
                missing = []
                for pair in ((data, has_data), (rec, has_rec)):
                    missing.extend([item for item, has in zip(*pair) if not
                                    has])
                logger.warning('Eager task {t} has missing output: {m}'
                               .format(t=eager_task.funcname, m=missing))
                return False
        return True

    @staticmethod
    def _split_eager(tasks):
        halt_eager = False
        eager_pipeline, pipeline = [], []
        for task in tasks:
            if task.is_eager and not halt_eager:
                eager_pipeline.append(task)
            else:
                if task.is_eager:
                    logger.debug('Not able to compute eager function "{}" on '
                                 'all pixels at once  because it came after '
                                 'non-eager tasks.'.format(task.funcname))
                    halt_eager = True
                pipeline.append(task)

        return eager_pipeline, pipeline

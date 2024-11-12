import ast
from abc import ABC, abstractmethod
from app.config import config
from app.models import const


# Base class for state management
class BaseState(ABC):
    @abstractmethod
    def update_task(self, task_id: str, state: int, progress: int = 0, **kwargs):
        pass

    @abstractmethod
    def get_task(self, task_id: str):
        pass


# Memory state management
class MemoryState(BaseState):
    def __init__(self):
        self._tasks = {}

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs,
    ):
        """Update the state and progress of a task.

        This function updates the specified task's state and progress in the
        internal task management system. It ensures that the progress value does
        not exceed 100. Additional keyword arguments can be provided to update
        other attributes of the task.

        Args:
            task_id (str): The unique identifier of the task to be updated.
            state (int?): The new state of the task. Defaults to const.TASK_STATE_PROCESSING.
            progress (int?): The progress percentage of the task. Defaults to 0.
        """

        progress = int(progress)
        if progress > 100:
            progress = 100

        self._tasks[task_id] = {
            "state": state,
            "progress": progress,
            **kwargs,
        }

    def get_task(self, task_id: str):
        return self._tasks.get(task_id, None)

    def delete_task(self, task_id: str):
        """Delete a task from the task list.

        This function removes a task identified by its unique task ID from the
        internal task storage. If the provided task ID does not exist in the
        task list, no action is taken.

        Args:
            task_id (str): The unique identifier of the task to be deleted.
        """

        if task_id in self._tasks:
            del self._tasks[task_id]


# Redis state management
class RedisState(BaseState):
    def __init__(self, host="localhost", port=6379, db=0, password=None):
        import redis

        self._redis = redis.StrictRedis(host=host, port=port, db=db, password=password)

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs,
    ):
        """Update the state and progress of a task in the Redis database.

        This function updates the specified task's state and progress in the
        Redis database. It ensures that the progress value does not exceed 100
        and allows for additional fields to be updated through keyword
        arguments.

        Args:
            task_id (str): The unique identifier of the task to be updated.
            state (int?): The new state of the task. Defaults to
                const.TASK_STATE_PROCESSING.
            progress (int?): The current progress of the task,
                represented as a percentage. Defaults to 0.
            **kwargs: Additional fields to update in the task.
        """

        progress = int(progress)
        if progress > 100:
            progress = 100

        fields = {
            "state": state,
            "progress": progress,
            **kwargs,
        }

        for field, value in fields.items():
            self._redis.hset(task_id, field, str(value))

    def get_task(self, task_id: str):
        """Retrieve a task from the Redis database using its task ID.

        This function fetches the task data associated with the given task ID
        from a Redis database. If the task data is found, it decodes the keys
        from bytes to strings and converts the values to their original types
        before returning the task as a dictionary. If no task data is found, it
        returns None.

        Args:
            task_id (str): The unique identifier for the task to be retrieved.

        Returns:
            dict or None: A dictionary containing the task data if found,
            or None if no task data exists for the given task ID.
        """

        task_data = self._redis.hgetall(task_id)
        if not task_data:
            return None

        task = {
            key.decode("utf-8"): self._convert_to_original_type(value)
            for key, value in task_data.items()
        }
        return task

    def delete_task(self, task_id: str):
        self._redis.delete(task_id)

    @staticmethod
    def _convert_to_original_type(value):
        """Convert the value from byte string to its original data type.

        This function attempts to decode a byte string into its original
        representation. It first decodes the byte string to a UTF-8 string and
        then tries to evaluate it as a Python literal. If the evaluation fails,
        it checks if the string represents an integer and converts it
        accordingly. Additional data type conversions can be added as needed.

        Args:
            value (bytes): The byte string to be converted.

        Returns:
            The original data type of the input value, which could be a list,
            integer, or string.
        """
        value_str = value.decode("utf-8")

        try:
            # try to convert byte string array to list
            return ast.literal_eval(value_str)
        except (ValueError, SyntaxError):
            pass

        if value_str.isdigit():
            return int(value_str)
        # Add more conversions here if needed
        return value_str


# Global state
_enable_redis = config.app.get("enable_redis", False)
_redis_host = config.app.get("redis_host", "localhost")
_redis_port = config.app.get("redis_port", 6379)
_redis_db = config.app.get("redis_db", 0)
_redis_password = config.app.get("redis_password", None)

state = (
    RedisState(
        host=_redis_host, port=_redis_port, db=_redis_db, password=_redis_password
    )
    if _enable_redis
    else MemoryState()
)

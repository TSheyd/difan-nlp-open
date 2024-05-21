from dagster import (Definitions, load_assets_from_modules, schedule, define_asset_job, AssetSelection,
                     FilesystemIOManager, DefaultScheduleStatus)
from dagster_docker import docker_executor

from . import assets

all_assets = load_assets_from_modules([assets])

news_parsing = define_asset_job(
    "news_parsing",
    AssetSelection.groups("parsing_new_data"),
    executor_def=docker_executor
)


@schedule(cron_schedule="10 22 * * *", execution_timezone="Europe/Moscow",
          job=news_parsing, default_status=DefaultScheduleStatus.RUNNING)
def load_data(_context):
    return {}


news_inference = define_asset_job("news_inference", selection='*load_data', executor_def=docker_executor)


@schedule(cron_schedule="50 22 * * *", execution_timezone="Europe/Moscow",
          job=news_inference, default_status=DefaultScheduleStatus.RUNNING)
def process_data(_context):
    return {}


# Storage for scheduled runs
io_manager = FilesystemIOManager(
    base_dir="data",  # Path is built relative to where `dagster dev` is run
)


defs = Definitions(
    assets=all_assets,
    schedules=[load_data, process_data],
    resources={
        'io_manager': io_manager,
    },
)
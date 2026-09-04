"""comradar — 커뮤니티 불편 신호 모니터링 프레임워크.

한 커뮤니티당 수집 에이전트 하나, 그 결과를 묶는 분석 에이전트 하나,
한 장짜리 보고서를 쓰는 보고 에이전트 하나로 구성된다.
"""

from .config import AppConfig, load_config
from .pipeline import Pipeline, RunResult
from .state import Store

__version__ = "0.1.0"
__all__ = ["AppConfig", "load_config", "Pipeline", "RunResult", "Store", "__version__"]

import logging
import pandas as pd

from typing import Iterable
from copy import deepcopy
from abc import ABCMeta, abstractmethod
from collections import defaultdict

logger = logging.getLogger(__name__)

_types = {}


def preprocessor(preprocessor_type):
    def wrapper(cls):
        if preprocessor_type in _types:
            raise ValueError(
                "Preprocessor with name '%s' has already been added" % preprocessor_type
            )
        _types[preprocessor_type] = cls
        return cls

    return wrapper


def create_preprocessor(preprocessor_type, *args, **kwargs):
    if preprocessor_type not in _types:
        raise ValueError("Can't find a preprocessor with name '%s'" % preprocessor_type)
    return _types[preprocessor_type](*args, **kwargs)


def normalize_preprocessor(value):
    if isinstance(value, dict):
        if "type" not in value:
            raise ValueError("A preprocessor type is empty")
        value = deepcopy(value)
        preprocessor_type = value.pop("type")
        return create_preprocessor(preprocessor_type, **value)
    return value


class Preprocessor(metaclass=ABCMeta):
    @abstractmethod
    def reset(self):
        ...

    @abstractmethod
    def prepare_series(self, series: Iterable[pd.Series]) -> Iterable[pd.Series]:
        ...

    @abstractmethod
    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        ...


@preprocessor("fill_gaps")
class FillGapsPreprocessor(Preprocessor):
    def __init__(self, gap_size, replace_value):
        if isinstance(gap_size, str):
            gap_size = pd.Timedelta(gap_size)
        self.gap_size = gap_size
        self.replace_value = replace_value
        self._gaps = defaultdict(list)

    def reset(self):
        self._gaps = defaultdict(list)

    def prepare_series(self, series: Iterable[pd.Series]) -> Iterable[pd.Series]:
        result = []
        for value in series:
            result.append(value)
            name = value.name
            idx = value.index.to_series()
            df = pd.concat([idx, idx.diff().rename("Diff")], axis=1)
            filtered_df = df[df["Diff"] > self.gap_size]
            gaps = (
                (row["Time"], row["Time"] + row["Diff"])
                for _, row in filtered_df.iterrows()
            )

            self._gaps[name].extend(gaps)
        for name, gaps in self._gaps.items():
            logger.info(
                "Found %d gap%s in '%s' time-series",
                len(gaps),
                "s" if len(gaps) > 1 else "",
                name,
            )
        return result

    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        for name, gaps in self._gaps.items():
            for gap_start, gap_end in gaps:
                df.iloc[
                    (df.index > gap_start) & (df.index < gap_end),
                    df.columns.get_loc(name),
                ] = self.replace_value
        return df
# Copyright 2024 Arjun Ashok
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import copy
import random
import warnings
import json
from pathlib import Path
warnings.simplefilter(action="ignore", category=FutureWarning)
warnings.simplefilter(action="ignore", category=UserWarning)

import numpy as np
import pandas as pd
from tqdm import tqdm
from gluonts.dataset.common import ListDataset
from gluonts.dataset.repository.datasets import get_dataset
from gluonts.transform import InstanceSampler
from pandas.tseries.frequencies import to_offset

from data.read_new_dataset import get_ett_dataset, create_train_dataset_without_last_k_timesteps, TrainDatasets, MetaData

class CombinedDatasetIterator:
    def __init__(self, datasets, seed, weights):
        self._datasets = [iter(el) for el in datasets]
        self._weights = weights
        self._rng = random.Random(seed)
        
    def __next__(self):
        (dataset,) = self._rng.choices(self._datasets, weights=self._weights, k=1)
        return next(dataset)


class CombinedDataset:
    def __init__(self, datasets, seed=None, weights=None):
        self._seed = seed
        self._datasets = datasets
        self._weights = weights
        n_datasets = len(datasets)
        if weights is None:
            self._weights = [1 / n_datasets] * n_datasets

    def __iter__(self):
        return CombinedDatasetIterator(self._datasets, self._seed, self._weights)

    def __len__(self):
        return sum([len(ds) for ds in self._datasets])


class SingleInstanceSampler(InstanceSampler):
    """
    Randomly pick a single valid window in the given time series.
    This fix the bias in ExpectedNumInstanceSampler which leads to varying sampling frequency
    of time series of unequal length, not only based on their length, but when they were sampled.
    """

    """End index of the history"""

    def __call__(self, ts: np.ndarray) -> np.ndarray:
        a, b = self._get_bounds(ts)
        window_size = b - a + 1
        if window_size <= 0:
            return np.array([], dtype=int)
        indices = np.random.randint(window_size, size=1)
        return indices + a


def _count_timesteps(
    left: pd.Timestamp, right: pd.Timestamp, delta: pd.DateOffset
) -> int:
    """
    Count how many timesteps there are between left and right, according to the given timesteps delta.
    If the number if not integer, round down.
    """
    # This is due to GluonTS replacing Timestamp by Period for version 0.10.0.
    # Original code was tested on version 0.9.4
    if type(left) == pd.Period:
        left = left.to_timestamp()
    if type(right) == pd.Period:
        right = right.to_timestamp()
    assert (
        right >= left
    ), f"Case where left ({left}) is after right ({right}) is not implemented in _count_timesteps()."
    try:
        return (right - left) // delta
    except TypeError:
        # For MonthEnd offsets, the division does not work, so we count months one by one.
        for i in range(10000):
            if left + (i + 1) * delta > right:
                return i
        else:
            raise RuntimeError(
                f"Too large difference between both timestamps ({left} and {right}) for _count_timesteps()."
            )

from pathlib import Path
from gluonts.dataset.common import ListDataset
from gluonts.dataset.repository.datasets import get_dataset

def create_train_dataset_last_k_percentage(
    raw_train_dataset,
    freq,
    k=100
):
    # Get training data
    train_data = []
    for i, series in enumerate(raw_train_dataset):
        s_train = series.copy()
        number_of_values = int(len(s_train["target"]) * k / 100)
        train_start_index = len(s_train["target"]) - number_of_values
        s_train["target"] = s_train["target"][train_start_index:]
        train_data.append(s_train)

    train_data = ListDataset(train_data, freq=freq)

    return train_data

def create_train_and_val_datasets_with_dates(
    name,
    dataset_path,
    data_id,
    history_length,
    prediction_length=None,
    num_val_windows=None,
    val_start_date=None,
    train_start_date=None,
    freq=None,
    last_k_percentage=None
):
    """
    Train Start date is assumed to be the start of the series if not provided
    Freq is not given is inferred from the data
    We can use ListDataset to just group multiple time series - https://github.com/awslabs/gluonts/issues/695
    """

    if name in ("ett_h1", "ett_h2", "ett_m1", "ett_m2"):
        path = "datasets/ett_datasets"
        raw_dataset = get_ett_dataset(name, path)
    elif name in ("cpu_limit_minute", "cpu_usage_minute", \
                        "function_delay_minute", "instances_minute", \
                        "memory_limit_minute", "memory_usage_minute", \
                        "platform_delay_minute", "requests_minute","缓0","缓1","缓2","缓3","速0","速1","速2","房早","室早","室早315" ):
        path = "datasets/ECG1/" + name + ".json"
        with open(path, "r") as f: data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_data = [x for x in data["train"] if type(x["target"][0]) != str]
        test_data = [x for x in data["test"] if type(x["target"][0]) != str]
        train_ds = ListDataset(train_data, freq=metadata.freq)
        test_ds = ListDataset(test_data, freq=metadata.freq)
        raw_dataset = TrainDatasets(metadata=metadata, train=train_ds, test=test_ds)
    elif name in ("beijing_pm25","beijing_pm25-1",  "beijing_multisite", "data2"):#"AirQualityUCI",
        path = "datasets/air_quality/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=24)
        raw_dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)
    elif name in ("30_0","30_1", "31_0","31_1","32_0","32_1","33_0","33_1", "34_0","34_1","35_0","35_1","36_0","36_1", "37_0","37_1","38_0","38_1","39_0","39_1","41_0","41_1",
                  "43_0","43_1", "44_0","44_1","45_0","45_1","46_0","46_1", "47_0","47_1","48_0","48_1", "50_0","50_1","51_0","51_1", "52_0","52_1", ):
        path = "datasets/ecg/30minscd/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=24)
        raw_dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)


    elif name in ("14046_0","14046_1", "14134_0","14134_1","14149_0","14149_1","14157_0","14157_1", "14172_0","14172_1",
                  "14184_0","14184_1","15814_0","15814_1",):
        path = "datasets/ecg/30min_long_term_ecg/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=24)
        raw_dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

    elif name in ("16265_0","16272_0", "16273_0","16420_0","16483_0", "16539_0","16773_0","16786_0","16795_0","17052_0","17453_0","18177_0","18184_0","19088_0","19090_0","19093_0","19140_0","19830_0"):
        path = "datasets/ecg/nsrdb/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=25)
        raw_dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

    elif name in ("100_0","101_0","102_0","103_0","104_0","105_0","106_0","107_0","108_0","109_0",
                  "111_0","112_0","113_0","114_0","115_0","116_0","117_0","118_0","119_0",
                  "121_0","122_0","123_0","124_0",
                  "200_0","201_0","202_0","203_0","205_0","207_0","208_0","209_0", "210_0","212_0","213_0","214_0","215_0","217_0","119_0",
                  "220_0","221_0","222_0","223_0","228_0","230_0","231_0","232_0","233_0","234_0",):
        path = "datasets/ecg/mitdb/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=24)
        raw_dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)
    elif name in ( "100_1","100_2", "100_3","100_4", "100_5","100_6", "100_7","100_8","100_9",
                   "100_10","100_11","100_12", "100_13","100_14", "100_15","100_16", "100_17","100_18","100_19",
                   "100_20","100_21","100_22", "100_23","100_24", "100_25","100_26", "100_27","100_28","100_29",
                   "100_30", "100_31", "100_32", "101_0","101_1","101_2", "103_0","103_1","108_0","108_1","108_2", "108_3","112_0","112_1",
                   ):
        path = "datasets/ecg/mitdbaf/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=360)
        raw_dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

    # elif name in ("A100", "A101", "A103", "A108","A112","A114","A118","A121","A124","A200","A201","A205","A215","A219","A220","A223","A231",
    #                   ):
    #     path = "datasets/ecg/mitdb_af/" + name + ".json"
    #     with open(path, "r") as f:
    #         data = json.load(f)
    #     metadata = MetaData(**data["metadata"])
    #     train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
    #     full_dataset = ListDataset(train_test_data, freq=metadata.freq)
    #     train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=25)
    #     raw_dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

    elif name in ("A100", "A101", "A103", "A108","A112","A114","A118","A121","A124","A200","A201","A205","A215","A219",
                  "A220","A223","A231","0","d1", ):
        path = "datasets/ecg/mitdb_af/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=25)
        raw_dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

    elif name in ( "0d","1","2","3","4","5","6","7","8","9","10","2-10","12d","12d-2Q","1d","房早","缓f"):
        path = "datasets/ecg/cmuecg/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=25)
        raw_dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

    elif name in ( "V100_0","V102_0", "V102_1","V102_2","V102_3","V104_0","V104_1","V105_0","V105_1","V107_0","V107_1","V108_0","V108_1","V109_0","V109_1","V109_2","V109_3","V109_4","V109_5","V109_6","V109_7","V116_0","V116_1","V116_2","V116_3","V116_4","V116_5","V118_1",
                   ):
        path = "datasets/ecg/mitdb_v/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=25)
        raw_dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

    elif name in ("V100", "V102", "V104", "V105", "V107", "V108", "V109", "V116", "V118", "V124", "V202", "V202", "V205", "V210", "V215", "V234"):
         path = "datasets/ecg/mitdbv/" + name + ".json"
         with open(path, "r") as f:
            data = json.load(f)
         metadata = MetaData(**data["metadata"])
         train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
         full_dataset = ListDataset(train_test_data, freq=metadata.freq)
         train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=25)
         raw_dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)



    else:
        raw_dataset = get_dataset(name, path=dataset_path)

    if prediction_length is None:
        prediction_length = raw_dataset.metadata.prediction_length
    if freq is None:
        freq = raw_dataset.metadata.freq
    timestep_delta = pd.tseries.frequencies.to_offset(freq)
    raw_train_dataset = raw_dataset.train

    if not num_val_windows and not val_start_date:
        raise Exception("Either num_val_windows or val_start_date must be provided")
    if num_val_windows and val_start_date:
        raise Exception("Either num_val_windows or val_start_date must be provided")

    max_train_end_date = None

    # Get training data
    total_train_points = 0
    train_data = []
    for i, series in enumerate(raw_train_dataset):
        s_train = series.copy()
        if val_start_date is not None:
            train_end_index = _count_timesteps(
                series["start"] if not train_start_date else train_start_date,
                val_start_date,
                timestep_delta,
            )
        else:
            train_end_index = len(series["target"]) - num_val_windows
        # Compute train_start_index based on last_k_percentage
        if last_k_percentage:
            number_of_values = int(len(s_train["target"]) * last_k_percentage / 100)
            train_start_index = train_end_index - number_of_values
        else:
            train_start_index = 0
        s_train["target"] = series["target"][train_start_index:train_end_index]
        s_train["item_id"] = i
        s_train["data_id"] = data_id
        train_data.append(s_train)
        total_train_points += len(s_train["target"])

        # Calculate the end date
        end_date = s_train["start"] + to_offset(freq) * (len(s_train["target"]) - 1)
        if max_train_end_date is None or end_date > max_train_end_date:
            max_train_end_date = end_date

    train_data = ListDataset(train_data, freq=freq)

    # Get validation data
    total_val_points = 0
    total_val_windows = 0
    val_data = []
    for i, series in enumerate(raw_train_dataset):
        s_val = series.copy()
        if val_start_date is not None:
            train_end_index = _count_timesteps(
                series["start"], val_start_date, timestep_delta
            )
        else:
            train_end_index = len(series["target"]) - num_val_windows
        val_start_index = train_end_index - prediction_length - history_length
        s_val["start"] = series["start"] + val_start_index * timestep_delta
        s_val["target"] = series["target"][val_start_index:]
        s_val["item_id"] = i
        s_val["data_id"] = data_id
        val_data.append(s_val)
        total_val_points += len(s_val["target"])
        total_val_windows += len(s_val["target"]) - prediction_length - history_length
    val_data = ListDataset(val_data, freq=freq)

    total_points = (
        total_train_points
        + total_val_points
        - (len(raw_train_dataset) * (prediction_length + history_length))
    )

    return (
        train_data,
        val_data,
        total_train_points,
        total_val_points,
        total_val_windows,
        max_train_end_date,
        total_points,
    )


def create_test_dataset(
    name, dataset_path, history_length, freq=None, data_id=None
):
    """
    For now, only window per series is used.
    make_evaluation_predictions automatically only predicts for the last "prediction_length" timesteps
    NOTE / TODO: For datasets where the test set has more series (possibly due to more timestamps), \
    we should check if we only use the last N series where N = series per single timestamp, or if we should do something else.
    """

    if name in ("ett_h1", "ett_h2", "ett_m1", "ett_m2"):
        path = "datasets/ett_datasets"
        dataset = get_ett_dataset(name, path)
    elif name in ("cpu_limit_minute", "cpu_usage_minute", \
                        "function_delay_minute", "instances_minute", \
                        "memory_limit_minute", "memory_usage_minute", \
                        "platform_delay_minute", "requests_minute","缓0","缓1","缓2","缓3","速0","速1","速2","房早","室早","室早315" ):
        path = "datasets/ECG1/" + name + ".json"
        with open(path, "r") as f: data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_data = [x for x in data["train"] if type(x["target"][0]) != str]
        test_data = [x for x in data["test"] if type(x["target"][0]) != str]
        train_ds = ListDataset(train_data, freq=metadata.freq)
        test_ds = ListDataset(test_data, freq=metadata.freq)
        dataset = TrainDatasets(metadata=metadata, train=train_ds, test=test_ds)
    elif name in ("beijing_pm25", "AirQualityUCI", "beijing_multisite"):
        path = "datasets/air_quality/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=24)
        dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)



#scd
    elif name in ("30_0","30_1", "31_0","31_1","32_0","32_1","33_0","33_1", "34_0","34_1",):#"35_0","35_1","36_0","36_1", "37_0","37_1","38_0","38_1","39_0","39_1", "41_0","41_1",
                 # "43_0","43_1", "44_0","44_1","45_0","45_1","46_0","46_1", "47_0","47_1","48_0","48_1", "50_0","50_1","51_0","51_1", "52_0","52_1",):
        path = "datasets/ecg/30minscd/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=24)
        dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

#long term ecg
    elif name in ("14046_0","14046_1", "14134_0","14134_1","14149_0","14149_1","14157_0","14157_1", "14172_0","14172_1",
                  "14184_0","14184_1","15814_0","15814_1",):
        path = "datasets/ecg/30min_long_term_ecg/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=24)
        dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

#NSRDB
    elif name in ("16265_0","16272_0", "16273_0", "16420_0", "16483_0", "16539_0", "16773_0", "16786_0", "16795_0",
                  "17052_0", "17453_0", "18177_0", "18184_0", "19088_0", "19090_0", "19093_0", "19140_0", "19830_0"):
        path = "datasets/ecg/1minnsrdb/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=24)
        dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)
#mitdb
    elif name in ("100_0","101_0","102_0","103_0","104_0","105_0","106_0","107_0","108_0","109_0",
                  "111_0","112_0","113_0","114_0","115_0","116_0","117_0","118_0","119_0",
                  "121_0","122_0","123_0","124_0",
                  "200_0","201_0","202_0","203_0","205_0","207_0","208_0","209_0", "210_0","212_0","213_0","214_0","215_0","217_0","119_0",
                  "220_0","221_0","222_0","223_0","228_0","230_0","231_0","232_0","233_0","234_0",):
        path = "datasets/ecg/mitdb/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=24)
        dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)
    # mitdb AF
    elif name in ("100_1","100_2","100_3","100_4","100_5","100_6","100_7","100_8","100_9"):

        path = "datasets/ecg/mitdbaf/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=360)
        dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

    elif name in (
        "A100", "A101", "A103", "A108", "A112", "A114", "A118", "A121", "A124", "A200", "A201", "A205", "A215", "A219",
        "A220", "A223", "A231","0","d1",
        ):
        path = "datasets/ecg/mitdb_af/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=25)
        dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

    # mitdb V
    elif  name in ( "V100_0","V102_0", "V102_1","V102_2","V102_3","V104_0","V104_1","V105_0","V105_1","V107_0","V107_1","V108_0","V108_1","V109_0","V109_1","V109_2","V109_3","V109_4","V109_5","V109_6","V109_7","V116_0","V116_1","V116_2","V116_3","V116_4","V116_5","V118_1",
                   ):
        path = "datasets/ecg/mitdb_v/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=25)
        dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)


    elif name in ( "V100", "V102", "V104", "V105", "V107", "V108", "V109", "V116", "V118", "V124", "V202", "V202", "V205", "V210", "V215", "V234"  ):
        path = "datasets/ecg/mitdbv/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=25)
        dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

    elif name in ( "0d","1", "2", "3", "4", "5", "6", "7", "8", "9", "10","2-10" ,"12d","12d-2Q","d1" ,"房早","缓f"):
        path = "datasets/ecg/cmuecg/" + name + ".json"
        with open(path, "r") as f:
            data = json.load(f)
        metadata = MetaData(**data["metadata"])
        train_test_data = [x for x in data["data"] if type(x["target"][0]) != str]
        full_dataset = ListDataset(train_test_data, freq=metadata.freq)
        train_ds = create_train_dataset_without_last_k_timesteps(full_dataset, freq=metadata.freq, k=25)
        dataset = TrainDatasets(metadata=metadata, train=train_ds, test=full_dataset)

    else:
        dataset = get_dataset(name, path=dataset_path)

    if freq is None:
        freq = dataset.metadata.freq
    prediction_length = dataset.metadata.prediction_length
    data = []
    total_points = 0
    for i, series in enumerate(dataset.test):
        offset = len(series["target"]) - (history_length + prediction_length)
        if offset > 0:
            target = series["target"][-(history_length + prediction_length) :]
            data.append(
                {
                    "target": target,
                    "start": series["start"] + offset,
                    "item_id": i,
                    "data_id": data_id,
                }
            )
        else:
            series_copy = copy.deepcopy(series)
            series_copy["item_id"] = i
            series_copy["data_id"] = data_id
            data.append(series_copy)
        total_points += len(data[-1]["target"])
    return ListDataset(data, freq=freq), prediction_length, total_points
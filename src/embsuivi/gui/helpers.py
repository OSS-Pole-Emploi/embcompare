from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd
import streamlit as st
from loguru import logger

from ..embeddings_compare import EmbeddingComparison
from .load_utils import EMBEDDING_FORMATS, FREQUENCIES_FORMATS


def round_sig(value: float, n_digits: int = 2) -> float:
    """Round float to significant figures

    Args:
        value (float): float number
        n_digits (int, optional): number fo significant digits. Defaults to 2.

    Returns:
        float: float
    """
    return float(f"{value:.{n_digits}g}")


@st.cache(suppress_st_warning=True, allow_output_mutation=True, max_entries=3)
def load_embedding(
    embedding_path: str,
    embedding_format: str,
    frequencies_path: str = None,
    frequencies_format: str = None,
):
    try:
        loading_function = EMBEDDING_FORMATS[embedding_format.lower()]

        return loading_function(
            embedding_path,
            frequencies_path=frequencies_path,
            frequencies_format=frequencies_format,
        )
    except KeyError:
        st.error(
            f"embedding format shloud be one of `{', '.join(EMBEDDING_FORMATS)}` "
            f"but is `{embedding_format}`\n\n"
            f"Could not load {embedding_path}"
        )


class AdvancedParameters:
    n_neighbors: int = 25
    max_emb_size: int = 10000
    min_frequency: float = 0.0

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def selection(cls):

        with st.form("advanced_parameters_selection"):
            n_neighbors = st.number_input(
                "Number of neighbors to use in the comparison",
                min_value=1,
                max_value=1000,
                step=10,
                value=cls.n_neighbors,
                key="n_neighbors",
            )

            max_emb_size = st.number_input(
                "Maximum number of elements in the embeddings "
                "(help to reduce memory footprint) :",
                min_value=100,
                max_value=200000,
                step=10000,
                value=cls.max_emb_size,
                key="max_emb_size",
            )

            min_frequency = st.number_input(
                "Minimum freqency for embedding elements :",
                min_value=0.0,
                max_value=1.0,
                step=0.0001,
                value=cls.min_frequency,
                format="%f",
                key="min_frequency",
            )

            submitted = st.form_submit_button("Change parameters")

            if submitted:
                logger.info(
                    f"n_neighbors={n_neighbors}, "
                    f"max_emb_size={max_emb_size}, "
                    f"min_frequency={min_frequency}"
                )

        return cls(
            n_neighbors=n_neighbors,
            max_emb_size=max_emb_size,
            min_frequency=min_frequency,
        )


def load_embeddings_labels(
    embedding_config: dict, emb1_id: str, emb2_id: str
) -> Tuple[dict, dict]:
    labels = []
    for emb_id in (emb1_id, emb2_id):
        emb_infos = embedding_config[emb_id]

        if "labels" not in emb_infos:
            labels.append({})
            continue
        else:
            path = Path(emb_infos["labels"])

        labels_format = emb_infos.get("labels_format", path.suffix[1:])

        labels.append(FREQUENCIES_FORMATS[labels_format](path))

    return tuple(labels)


def display_neighborhoods_elements_comparison(
    comparison: EmbeddingComparison, elements: List[Tuple[str, float]]
):
    emb1, emb2 = comparison.embeddings
    emb1_labels, emb2_labels = comparison.labels

    least_similar_keys, least_similar_sim = list(zip(*elements))

    logger.info("Get first embedding neighbors...")
    neighborhoods_1 = emb1.get_neighbors(
        comparison.n_neighbors, keys=least_similar_keys
    )

    logger.info("Get second embedding neighbors...")
    neighborhoods_2 = emb2.get_neighbors(
        comparison.n_neighbors, keys=least_similar_keys
    )

    logger.info("Display neighbors comparisons...")
    for key, similarity in zip(least_similar_keys, least_similar_sim):

        label = emb1_labels.get(key, key)

        with st.expander(f"{label} (similarity {similarity:.0%})"):
            # Display frequencies
            for emb, col in zip((emb1, emb2), st.columns(2)):
                if emb.is_frequency_set():
                    with col:
                        freq = emb.get_frequency(key)
                        freq_str = f"{freq:.4f}" if freq > 0.0001 else f"{freq:.1e}"

                        st.write(f"term ferquency : {freq_str}")

            neighbors1 = {k: s for k, s in neighborhoods_1[key]}
            neighbors2 = {k: s for k, s in neighborhoods_2[key]}

            # Display common neighbors
            common_neighbors = {
                k: i for i, k in enumerate(neighbors1) if k in neighbors2
            }

            if common_neighbors:
                st.subheader("common neighbors")
                st.table(
                    pd.DataFrame(
                        {
                            "neighbor": [
                                emb1_labels.get(k, k) for k in common_neighbors
                            ],
                            "sim1": [f"{neighbors1[k]:.1%}" for k in common_neighbors],
                            "sim2": [f"{neighbors2[k]:.1%}" for k in common_neighbors],
                        }
                    )
                )

            # Display other neighbors
            only1 = {
                k: i for i, k in enumerate(neighbors1) if k not in common_neighbors
            }
            only2 = {
                k: i for i, k in enumerate(neighbors2) if k not in common_neighbors
            }

            if only1:
                st.subheader("distinct neighbors")
                st.table(
                    pd.DataFrame(
                        {
                            "neighbor1": [emb1_labels.get(k, k) for k in only1],
                            "sim1": [f"{neighbors1[k]:.1%}" for k in only1],
                            "sim2": [f"{neighbors2[k]:.1%}" for k in only2],
                            "neighbor2": [emb2_labels.get(k, k) for k in only2],
                        }
                    )
                )


def weighted_median(values, weights):
    i = np.argsort(values)
    c = np.cumsum(weights[i])
    return values[i[np.searchsorted(c, 0.5 * c[-1])]]


def compute_weighted_median_similarity(comparison: EmbeddingComparison):
    emb1, emb2 = comparison.embeddings

    freqs_1 = np.array(
        [emb1.get_frequency(k) for k in comparison.neighborhoods_similarities]
    )
    freqs_2 = np.array(
        [emb2.get_frequency(k) for k in comparison.neighborhoods_similarities]
    )
    freqs_mean = (freqs_1 + freqs_2) / 2

    return weighted_median(comparison.neighborhoods_similarities_values, freqs_mean)


def compute_weighted_median_ordered_similarity(comparison: EmbeddingComparison):
    emb1, emb2 = comparison.embeddings

    freqs_1 = np.array(
        [emb1.get_frequency(k) for k in comparison.neighborhoods_ordered_similarities]
    )
    freqs_2 = np.array(
        [emb2.get_frequency(k) for k in comparison.neighborhoods_ordered_similarities]
    )
    freqs_mean = (freqs_1 + freqs_2) / 2

    return weighted_median(
        comparison.neighborhoods_ordered_similarities_values, freqs_mean
    )

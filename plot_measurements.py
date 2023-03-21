import os
import sys
import math
import json

from datetime import datetime
from time import sleep

import matplotlib.pyplot as plt

from tune_and_monitor import is_frequency_ignored, get_ignored_frequencies


def get_measurements(measurements_file_path):
    measurements = []
    with open(measurements_file_path, encoding='utf-8') as file:
        for line in file:
            values = line.split(',')
            measurements.append({
                'timestamp': int(math.floor(float(values[0]))),
                'datetime': values[1],
                'frequency': int(values[2]),
                'ignored': int(values[3])
            })
    return measurements


def plot_measurements():
    config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), sys.argv[1])
    with open(config_file_path) as file:
        config = json.loads(file.read())
    home_dir = os.path.dirname(os.path.abspath(__file__))
    graphs_dir_path = config.get('graphs_dir_path', os.path.join(home_dir, 'graphs'))
    timestamp = datetime.today()
    dir_name = timestamp.strftime('%y_%m_%d')
    dir_path = os.path.join(graphs_dir_path, dir_name)
    measurements_file_path = os.path.join(dir_path, 'measurements.csv')

    measurements = get_measurements(measurements_file_path)

    min_frequency = min(measurements, key=lambda v: v['frequency'])['frequency']
    max_frequency = max(measurements, key=lambda v: v['frequency'])['frequency']
    min_timestamp = min(measurements, key=lambda v: v['timestamp'])['timestamp']
    max_timestamp = max(measurements, key=lambda v: v['timestamp'])['timestamp']

    plt.cla()
    plt.clf()
    plt.close()

    ax = plt.axes()
    ax.grid(which='major', linestyle='-', linewidth=0.2)
    ax.grid(which='minor', linestyle='--', alpha=0.3, linewidth=0.2)

    frequency_margin = (max_frequency - min_frequency) * 0.025
    timestamp_margin = (max_timestamp - min_timestamp) * 0.025
    ax.set_xlim(min_frequency - frequency_margin, max_frequency + frequency_margin)
    ax.set_ylim(max_timestamp + timestamp_margin, min_timestamp - timestamp_margin)

    ratio = 0.6
    xleft, xright = ax.get_xlim()
    ybottom, ytop = ax.get_ylim()
    ax.set_aspect(abs((xright - xleft) / (ybottom - ytop)) * ratio)

    if max_timestamp - min_timestamp <= 60:
        ax.yaxis.set_major_locator(plt.MultipleLocator(1))
    elif max_timestamp - min_timestamp <= 60 * 60:
        ax.yaxis.set_major_locator(plt.MultipleLocator(60))
    elif max_timestamp - min_timestamp < 60 * 60 * 4:
        ax.yaxis.set_major_locator(plt.MultipleLocator(60 * 5))
    else:
        ax.yaxis.set_major_locator(plt.MultipleLocator(60 * 60 * 30))

    if max_frequency - min_frequency <= 10_000_000:
        ax.xaxis.set_major_locator(plt.MultipleLocator(1_000_000))
        ax.xaxis.set_minor_locator(plt.MultipleLocator(100_000))
    elif max_frequency - min_frequency <= 100_000_000:
        ax.xaxis.set_major_locator(plt.MultipleLocator(10_000_000))
        ax.xaxis.set_minor_locator(plt.MultipleLocator(1_000_000))
    elif 200 < max_frequency - min_frequency <= 1000_000_000:
        ax.xaxis.set_major_locator(plt.MultipleLocator(100_000_000))
        ax.xaxis.set_minor_locator(plt.MultipleLocator(10_000_000))
    elif max_frequency - min_frequency > 1000_000_000:
        ax.xaxis.set_major_locator(plt.MultipleLocator(100_000_000))
        ax.xaxis.set_minor_locator(plt.MultipleLocator(10_000_000))

    ax.tick_params(axis='y', which='major', labelsize=4)
    ax.tick_params(axis='x', which='major', labelsize=4, rotation=90)
    ax.tick_params(axis='x', which='minor', labelsize=3, rotation=90, labelcolor='grey')

    def format_x_func(value, tick_number):
        return '{:d}'.format(int(value / 1_000_000))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(format_x_func))
    ax.xaxis.set_minor_formatter(plt.FuncFormatter(format_x_func))

    def format_y_func(value, tick_number):
        return datetime.fromtimestamp(value).strftime('%H:%M:%S')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(format_y_func))

    ignored_frequencies = get_ignored_frequencies(config_file_path)

    plotted_frequencies = []
    for measurement in measurements:
        timestamp = measurement['timestamp']
        frequency = measurement['frequency']
        ignored = is_frequency_ignored(frequency, ignored_frequencies)

        if ignored:
            color = 'grey'
        else:
            color = 'red'
            file_name = '{}-{:03d}_{:03d}_{:03d}.pdf'.format(
                datetime.fromtimestamp(timestamp).strftime('%H_%M_%S'),
                int(frequency / 1_000_000),
                int(frequency % 1_000_000 / 1_000),
                int(frequency % 1_000)
            )
            url = "file:///{}/{}".format('./measurements', file_name)
            plt.text(frequency, timestamp, 'o', alpha=0, fontsize=3, url=url)

        plt.plot(frequency, timestamp, color=color, marker='o', linestyle='dashed', linewidth=1, markersize=0.3)

        if frequency not in plotted_frequencies:
            plt.axvline(x=frequency, color='grey', linestyle='dashed', linewidth=0.2)
            plotted_frequencies.append(frequency)

    plt.xticks(rotation=90)

    output_file_path = os.path.join(os.path.dirname(measurements_file_path), 'measurements.pdf')
    plt.savefig(output_file_path)
    print('Generated PDF file {}'.format(output_file_path))


if __name__ == '__main__':
    while True:
        plot_measurements()
        sleep(5)

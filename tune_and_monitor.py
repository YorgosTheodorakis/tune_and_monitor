import io
import os
import csv
import time
import json
import logging
import argparse
import subprocess

import matplotlib.pyplot as plt

from datetime import datetime
from time import sleep


def get_logger(log_file_path):
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    logger.addHandler(stream_handler)

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    logger.info('Tuning to the radio frequencies.')
    return logger


def get_args(home_dir):
    parser = argparse.ArgumentParser(description='Monitor for new radio signals.')
    parser.add_argument('-l', '--log-file-path', default=os.path.join(home_dir, 'monitoring.log'), metavar='FILE', help='Path to the log file.')
    parser.add_argument('-c', '--config-file-path', default=os.path.join(home_dir, 'config.json'), metavar='FILE', help='Path to the config file.')
    args = parser.parse_args()
    return args


def generate_graph(file_path, interval_start, interval_end, tuned_frequency_mean, monitor_frequency_mean, frequency, logger, ignored_frequencies):
    plt.cla()
    plt.clf()
    plt.close()

    ax = plt.axes()
    ax.grid(which='major', linestyle='--', alpha=0.5, linewidth=0.5)
    ax.grid(which='minor', linestyle='--', alpha=0.3, linewidth=0.2)
    ax.set_xlim(interval_start * 1_000_000, interval_end * 1_000_000)
    ax.set_ylim(-100, 0)

    ratio = 0.5625
    xleft, xright = ax.get_xlim()
    ybottom, ytop = ax.get_ylim()
    ax.set_aspect(abs((xright - xleft) / (ybottom - ytop)) * ratio)

    ax.yaxis.set_major_locator(plt.MultipleLocator(10))
    if interval_end - interval_start <= 20:
        ax.xaxis.set_major_locator(plt.MultipleLocator(1_000_000))
        ax.xaxis.set_minor_locator(plt.MultipleLocator(250_000))
    elif interval_end - interval_start < 200:
        ax.xaxis.set_major_locator(plt.MultipleLocator(10_000_000))
        ax.xaxis.set_minor_locator(plt.MultipleLocator(1_000_000))
    elif 200 < interval_end - interval_start < 1000:
        ax.xaxis.set_major_locator(plt.MultipleLocator(50_000_000))
        ax.xaxis.set_minor_locator(plt.MultipleLocator(10_000_000))
    elif interval_end - interval_start > 1000:
        ax.xaxis.set_major_locator(plt.MultipleLocator(100_000_000))
        ax.xaxis.set_minor_locator(plt.MultipleLocator(10_000_000))

    ax.tick_params(axis='both', which='major', labelsize=4)
    ax.tick_params(axis='x', which='major', labelsize=4, rotation=90)
    ax.tick_params(axis='x', which="minor", labelsize=3, rotation=90, labelcolor='grey')

    def format_func(value, tick_number):
        return '{:d}'.format(int(value / 1000000))

    ax.xaxis.set_major_formatter(plt.FuncFormatter(format_func))
    ax.xaxis.set_minor_formatter(plt.FuncFormatter(format_func))

    sorted_tuned_frequency_mean_keys = sorted(tuned_frequency_mean)
    sorted_tuned_frequency_mean_values = [tuned_frequency_mean[f] for f in sorted_tuned_frequency_mean_keys]
    plt.plot(sorted_tuned_frequency_mean_keys, sorted_tuned_frequency_mean_values, label='Tuned signal', linewidth='0.5')
    if monitor_frequency_mean:
        sorted_monitor_frequency_mean_keys = sorted(monitor_frequency_mean)
        sorted_monitor_frequency_mean_values = [monitor_frequency_mean[f] for f in sorted_tuned_frequency_mean_keys]
        plt.plot(sorted_monitor_frequency_mean_keys, sorted_monitor_frequency_mean_values, label='Monitored signal', linewidth='0.25')

    for ignored_frequency in ignored_frequencies:
        plt.axvspan(ignored_frequency['start'], ignored_frequency['end'], color='grey', alpha=0.33)

    if frequency:
        plt.axvspan(frequency - 500_000, frequency + 500_000, color='green', alpha=0.2)
        plt.title('Frequency {:.3f} MHz'.format(frequency / 1_000_000))

        monitored_frequency_power = monitor_frequency_mean[frequency]
        tuned_frequency_power = tuned_frequency_mean[frequency]
        plt.axvline(x=frequency, color='#000000', linestyle='solid', linewidth=0.1)
        plt.axhline(y=monitored_frequency_power, color='#ff00aa', linestyle='solid', linewidth=0.3) # TODO Remove.
        plt.axhline(y=tuned_frequency_power, color='#00ffaa', linestyle='solid', linewidth=0.3) # TODO Remove.

    plt.savefig(file_path)
    logger.warning('Generated file {}'.format(file_path))


def get_intervals(included_frequencies):
    intervals = []
    for included_frequency in included_frequencies:
        frequencies = get_frequencies(
            included_frequency['start'],
            included_frequency['end'],
            included_frequency['width'],
            included_frequency.get('excluded_frequencies', [])
        )
        intervals.extend(frequencies)
    return intervals


def get_frequencies(included_frequency_start, included_frequency_end, included_frequency_width, excluded_frequencies):
    if not excluded_frequencies:
        return [
            {
                'start': included_frequency_start,
                'end': included_frequency_end,
                'width': included_frequency_width
            }
        ]
    else:
        return [
            {
                'start': included_frequency_start,
                'end': excluded_frequencies[0]['start'],
                'width': included_frequency_width
            }
        ] + get_frequencies(
            excluded_frequencies[0]['end'],
            included_frequency_end,
            included_frequency_width,
            excluded_frequencies[1:]
        )


def update_krakensdr_center_frequency(frequency, krakensdr_config_file_path):
    with open(krakensdr_config_file_path, 'r', encoding='utf-8') as file:
        krakensdr_config = json.loads(file.read())

    if abs(float(krakensdr_config['center_freq']) - float(frequency)) > 0.1:
        krakensdr_config['center_freq'] = frequency
        with open(krakensdr_config_file_path, 'w', encoding='utf-8') as file:
            file.write(json.dumps(krakensdr_config, indent=4))


def get_ignored_frequencies(config_file_path):
    with open(config_file_path) as file:
        config = json.loads(file.read())

    ignored_frequencies = config.get('ignored_frequencies', [])
    for ignored_frequency in ignored_frequencies:
        if 'start' not in ignored_frequency or 'end' not in ignored_frequency and \
           'center' in ignored_frequency and 'span' in ignored_frequency:
            ignored_frequency['start'] = ignored_frequency['center'] - ignored_frequency['span']
            ignored_frequency['end'] = ignored_frequency['center'] + ignored_frequency['span']

    return ignored_frequencies


def is_frequency_ignored(frequency, ignored_frequencies):
    for ignored_frequency in ignored_frequencies:
        if ignored_frequency['start'] <= frequency <= ignored_frequency['end']:
            return True


def scan_frequencies(number_of_measurements, start, end, width, lna_gain, vga_gain, rx_amp, bias_tee, logger, integration_enabled=False):
    command = [
        'hackrf_sweep',
        '-l {}'.format(lna_gain),
        '-g {}'.format(vga_gain),
        '-a {}'.format(rx_amp),
        '-p {}'.format(bias_tee),
        '-N {}'.format(number_of_measurements),
        '-f {}:{}'.format(start, end),
        '-w {}'.format(width)
    ]

    logger.info('Running command "{}"'.format(' '.join(command)))
    hackrf_sweep_start = time.time()
    for _ in range(3):
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception:
            logger.error('Exception occurred when running command "{}"'.format(command))
            sleep(10)
            continue

        if result.returncode != 0:
            logger.error('Failed to get data from HackRF One.')
            logger.error('\n' + result.stderr.decode().strip())

            # Wait for 10 seconds and try reading from HackRF One again.
            sleep(10)
        else:
            break
    logger.debug('Reading output from HackRF One')
    output = result.stdout.decode()
    logger.debug('Received output from HackRF One')

    hackrf_sweep_end = time.time()
    logger.debug('hackrf_sweep: {:.2f}'.format(hackrf_sweep_end - hackrf_sweep_start))

    frequency = start * 1_000_000
    measurements = dict()
    if integration_enabled:
        values = output.split(',')
        for value in values[:-1]:
            measurements[frequency] = float(value)
            frequency += width
    else:
        csvreader = csv.reader(io.StringIO(output), delimiter=',', skipinitialspace=True)
        measurements_sum = dict()
        measurements_count = dict()
        for line in csvreader:
            hz_low = int(line[2])

            for number, value in enumerate(line[6:], start=1):
                # Calculate the frequency for each bin and convert to MHz
                frequency = int(hz_low + (int(width) * number) - (int(width) / 2))
                # Ignore frequencies that fall outside the measurement range.
                if start * 1_000_000 < frequency < end * 1_000_000:
                    if frequency not in measurements_sum:
                        measurements_sum[frequency] = 0.0
                        measurements_count[frequency] = 0.0
                    measurements_sum[frequency] += float(value)
                    measurements_count[frequency] += 1

        for frequency in measurements_sum:
            measurements[frequency] = measurements_sum[frequency] / measurements_count[frequency]
    return measurements


def main():
    home_dir = os.path.dirname(os.path.abspath(__file__))
    args = get_args(home_dir)
    logger = get_logger(args.log_file_path)
    config_file_path = os.path.join(home_dir, args.config_file_path)

    with open(config_file_path) as file:
        config = json.loads(file.read())

    intervals = get_intervals(config['included_frequencies'])
    lna_gain = config.get('lna_gain', 16)
    vga_gain = config.get('vga_gain', 16)
    rx_amp = config.get('rx_amp', 0)
    bias_tee = config.get('bias_tee', 0)
    tune_number_of_samples = config.get('tune_number_of_samples', 200)
    monitor_number_of_samples = config.get('monitor_number_of_samples', 20)
    sensitivity = config.get('sensitivity', 10)
    graphs_dir_path = config.get('graphs_dir_path', os.path.join(home_dir, 'graphs'))
    update_krakensdr = config.get('update_krakensdr', False)
    integration = config.get('integration', 1)
    tuning_period = config.get('tuning_period', 20)
    krakensdr_config_file_path = config.get('krakensdr_config_file_path', '')

    while True:
        logger.info('Tuning to the radio frequencies.')
        interval_tuned_frequency_mean = list()
        for interval_index in range(len(intervals)):
            interval_start = intervals[interval_index]['start']
            interval_end = intervals[interval_index]['end']
            interval_width = intervals[interval_index]['width']
            tuned_frequency_mean = scan_frequencies(
                tune_number_of_samples,
                interval_start,
                interval_end,
                interval_width,
                lna_gain,
                vga_gain,
                rx_amp,
                bias_tee,
                logger
            )
            interval_tuned_frequency_mean.append(tuned_frequency_mean)

        timestamp = datetime.today()
        dir_name = timestamp.strftime('%y_%m_%d')
        dir_path = os.path.join(graphs_dir_path, dir_name)
        if not os.path.isdir(dir_path):
            os.mkdir(dir_path)

        ignored_frequencies = get_ignored_frequencies(config_file_path)

        for interval_index in range(len(intervals)):
            interval_start = intervals[interval_index]['start']
            interval_end = intervals[interval_index]['end']
            tuned_frequency_mean = interval_tuned_frequency_mean[interval_index]

            file_name = '{}-tune-{}-{}.pdf'.format(
                timestamp.strftime('%H_%M_%S'),
                interval_start,
                interval_end
            )
            measurements_dir_path = os.path.join(dir_path, 'measurements')
            if not os.path.isdir(measurements_dir_path):
                os.mkdir(measurements_dir_path)
            file_path = os.path.join(measurements_dir_path, file_name)
            generate_graph(file_path, interval_start, interval_end, tuned_frequency_mean, dict(), 0, logger, ignored_frequencies)

        for _ in range(tuning_period):
            start = time.time()
            logger.info('Monitoring the radio frequencies.')

            ignored_frequencies = get_ignored_frequencies(config_file_path)

            for interval_index in range(len(intervals)):
                interval_start = intervals[interval_index]['start']
                interval_end = intervals[interval_index]['end']
                interval_width = intervals[interval_index]['width']

                monitor_frequency_mean = dict()
                for frequency in tuned_frequency_mean:
                    monitor_frequency_mean[frequency] = tuned_frequency_mean[frequency]

                for _ in range(integration):
                    temp_monitor_frequency_mean = scan_frequencies(
                        monitor_number_of_samples,
                        interval_start,
                        interval_end,
                        interval_width,
                        lna_gain,
                        vga_gain,
                        rx_amp,
                        bias_tee,
                        logger
                    )
                    for frequency in sorted(monitor_frequency_mean):
                        monitor_frequency_mean[frequency] += temp_monitor_frequency_mean[frequency] - tuned_frequency_mean[frequency]

                tuned_frequency_mean = interval_tuned_frequency_mean[interval_index]
                for frequency in monitor_frequency_mean:
                    if frequency not in tuned_frequency_mean:
                        logger.error('Frequency {:,} not found in tuned frequencies.'.format(frequency))
                    else:
                        if monitor_frequency_mean[frequency] >= tuned_frequency_mean[frequency] + sensitivity:
                            if not is_frequency_ignored(frequency, ignored_frequencies):
                                max_frequency = frequency
                                max_frequency_offset = monitor_frequency_mean[frequency] - tuned_frequency_mean[frequency]
                                for freq in monitor_frequency_mean:
                                    if not is_frequency_ignored(freq, ignored_frequencies):
                                        frequency_offset = monitor_frequency_mean[freq] - tuned_frequency_mean[freq]
                                        if frequency_offset > max_frequency_offset:
                                            max_frequency = freq
                                            max_frequency_offset = frequency_offset
                                frequency = max_frequency
                                logger.warning('{:,} Hz  ::  {:.2f} db > '
                                               ' {:.2f} db + {:.2f} db'.format(
                                    frequency,
                                    monitor_frequency_mean[frequency],
                                    tuned_frequency_mean[frequency],
                                    sensitivity
                                ))

                                timestamp = datetime.today()

                                file_name = '{}-{:03d}_{:03d}_{:03d}.pdf'.format(
                                    timestamp.strftime('%H_%M_%S'),
                                    int(frequency / 1_000_000),
                                    int(frequency % 1_000_000 / 1_000),
                                    int(frequency % 1_000)
                                )
                                file_path = os.path.join(dir_path, 'measurements', file_name)
                                generate_graph(file_path, interval_start, interval_end, tuned_frequency_mean, monitor_frequency_mean, frequency, logger, ignored_frequencies)

                                if update_krakensdr:
                                    update_krakensdr_center_frequency(frequency / 1_000_000, krakensdr_config_file_path)

                                ignored = False
                            else:
                                ignored = True

                            # Store frequency measurement.
                            with open(os.path.join(dir_path, 'measurements.csv'), 'a') as file:
                                line = '{},{},{},{}\n'.format(
                                    int(timestamp.timestamp()),
                                    timestamp.strftime('%H:%M:%S'),
                                    frequency,
                                    int(ignored)
                                )
                                file.write(line)
                            break
                sleep(0.25)
            end = time.time()
            logger.debug("Interval: {:.2f}".format(end - start))


if __name__ == '__main__':
    main()

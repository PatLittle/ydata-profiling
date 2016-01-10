# coding: utf-8

# In[106]:
from __future__ import division

import StringIO
import base64
import urllib
import os

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pandas.core.common as com

import formatters
import templates

DEFAULT_FLOAT_FORMATTER = u'pandas_profiling.__default_float_formatter'

NO_OUTPUTFILE = "pandas_profiling.no_outputfile"
DEFAULT_OUTPUTFILE = "pandas_profiling.default_outputfile"


def describe(df):
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be of type pandas.DataFrame")
    if df.empty:
        raise ValueError("df can not be empty")

    # reset matplotlib style before use
    matplotlib.style.use("default")
    matplotlib.style.use(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pandas_profiling.mplstyle"))

    def pretty_name(x):
        x *= 100
        if x == int(x):
            return '%.0f%%' % x
        else:
            return '%.1f%%' % x

    def describe_numeric_1d(series, base_stats):
        stats = {'mean': series.mean(), 'std': series.std(), 'variance': series.var(), 'min': series.min(),
                'max': series.max()}
        stats['range'] = stats['max'] - stats['min']

        for x in np.array([0.05, 0.25, 0.5, 0.75, 0.95]):
            stats[pretty_name(x)] = series.quantile(x)
        stats['iqr'] = stats['75%'] - stats['25%']
        stats['kurtosis'] = series.kurt()
        stats['skewness'] = series.skew()
        stats['sum'] = series.sum()
        stats['mad'] = series.mad()
        stats['cv'] = stats['std'] / stats['mean'] if stats['mean'] else np.NaN

        if base_stats['distinct_count'] < 100 and base_stats['count'] > 1000:
            stats['type'] = "DISCRETE"
        else:
            stats['type'] = "NUM"

        # Large histogram
        imgdata = StringIO.StringIO()
        plot = series.plot(kind='hist', figsize=(6, 4),
                           facecolor='#337ab7')  # TODO when running on server, send this off to a different thread
        plot.figure.subplots_adjust(left=0.15, right=0.95, top=0.9, bottom=0.1, wspace=0, hspace=0)
        plot.figure.savefig(imgdata)
        imgdata.seek(0)
        stats['histogram'] = 'data:image/png;base64,' + urllib.quote(base64.b64encode(imgdata.buf))
        plt.close(plot.figure)

        # Small histogram
        imgdata = StringIO.StringIO()
        plot = series.plot(kind='hist', figsize=(2, 0.75), facecolor='#337ab7')
        plot.axes.get_yaxis().set_visible(False)
        plot.set_axis_bgcolor("w")
        xticks = plot.xaxis.get_major_ticks()
        for tick in xticks[1:-1]:
            tick.set_visible(False)
            tick.label.set_visible(False)

        for tick in (xticks[0], xticks[-1]):
            tick.label.set_fontsize(8)

        plot.figure.subplots_adjust(left=0.15, right=0.85, top=1, bottom=0.35, wspace=0, hspace=0)
        plot.figure.savefig(imgdata)
        imgdata.seek(0)
        stats['mini_histogram'] = 'data:image/png;base64,' + urllib.quote(base64.b64encode(imgdata.buf))

        plt.close(plot.figure)

        return pd.Series(stats, name=series.name)

    def describe_date_1d(series):
        stats = {'min': series.min(), 'max': series.max()}
        stats['range'] = stats['max'] - stats['min']
        stats['type'] = "DATE"
        return pd.Series(stats, name=series.name)

    def describe_categorical_1d(data):
        # Only run if at least 1 non-missing value
        objcounts = data.value_counts()
        top, freq = objcounts.index[0], objcounts.iloc[0]
        names = []
        result = []

        if data.dtype == object or com.is_categorical_dtype(data.dtype):
            names += ['top', 'freq', 'type']
            result += [top, freq, 'CAT']

        return pd.Series(result, index=names, name=data.name)

    def describe_constant_1d(data):
        return pd.Series(['CONST'], index=['type'], name=data.name)

    def describe_unique_1d(data):
        return pd.Series(['UNIQUE'], index=['type'], name=data.name)

    def describe_1d(data):
        # Is unique
        # Percent missing
        names = ['count', 'distinct_count', 'p_missing', 'n_missing', 'is_unique', 'mode', 'p_unique', 'memorysize']
        count = data.count()
        leng = len(data)
        distinct_count = data.nunique(dropna=False)
        if count > distinct_count > 1:

            mode = data.mode().iloc[0]
        else:
            mode = data[0]

        results_data = [count, distinct_count, 1 - count / leng, leng - count, distinct_count == leng, mode,
                        distinct_count / count, data.memory_usage()]
        result = pd.Series(results_data, index=names, name=data.name)

        if distinct_count <= 1:
            result = result.append(describe_constant_1d(data))
        elif com.is_numeric_dtype(data):
            result = result.append(describe_numeric_1d(data, result))
        elif com.is_datetime64_dtype(data):
            result = result.append(describe_date_1d(data))
        elif distinct_count == leng:
            result = result.append(describe_unique_1d(data))
        else:
            result = result.append(describe_categorical_1d(data))
        return result

    ldesc = [describe_1d(s) for _, s in df.iteritems()]
    # set a convenient order for rows
    names = []
    ldesc_indexes = sorted([x.index for x in ldesc], key=len)
    for idxnames in ldesc_indexes:
        for name in idxnames:
            if name not in names:
                names.append(name)
    variable_stats = pd.concat(ldesc, join_axes=pd.Index([names]), axis=1)
    variable_stats.columns.names = df.columns.names

    table_stats = {'n': len(df), 'nvar': len(df.columns)}
    table_stats['total_missing'] = variable_stats.loc['n_missing'].sum() / (table_stats['n'] * table_stats['nvar'])

    memsize = df.memory_usage(index=True).sum()
    table_stats['memsize'] = formatters.fmt_bytesize(memsize)
    table_stats['recordsize'] = formatters.fmt_bytesize(memsize / table_stats['n'])

    table_stats.update({k: 0 for k in ("TEXT", "NUM", "DISCRETE", "DATE", "CONST", "CAT", "UNIQUE")})
    table_stats.update(dict(variable_stats.loc['type'].value_counts()))

    return {'table': table_stats, 'variables': variable_stats.T, 'freq': {k: df[k].value_counts() for k in df.columns}}


# (/TODO:, add, warnings, high, cardinality)
# (/, add, different, vartypes, for, measurements,
# (different, value, for, each, observation), dates,, lookup, keys=discrete,, ...)
#

def to_html(sample_df, stats_object, formatters=None):
    if formatters is None:
        formatters = {}
    if not isinstance(sample_df, pd.DataFrame):
        raise TypeError("sample_df must be of type pandas.DataFrame")

    if not isinstance(stats_object, dict):
        raise TypeError("stats_object must be of type dict. Did you generate this using the pandas_profiling.describe() function?")

    if stats_object.keys() != ['table', 'variables', 'freq']:
        raise TypeError("stats_object badly formatted. Did you generate this using the pandas_profiling-eda.describe() function?")

    if DEFAULT_FLOAT_FORMATTER not in formatters:
        formatters[DEFAULT_FLOAT_FORMATTER] = lambda v: str(float('{:.5g}'.format(v))).rstrip('0').rstrip('.')

    def fmt(value, name):
        if pd.isnull(value):
            return ""
        if name in formatters:
            return formatters[name](value)
        elif isinstance(value, float):
            return formatters[DEFAULT_FLOAT_FORMATTER](value)
        else:
            return str(value)

    def freq_table(freqtable, n, table_template, row_template, max_number_of_items_in_table):

        freq_rows_html = u''

        freq_other = sum(freqtable[max_number_of_items_in_table:])
        freq_missing = n - sum(freqtable)
        max_freq = max(freqtable.values[0], freq_other, freq_missing)
        try:
            min_freq = freqtable.values[max_number_of_items_in_table]
        except IndexError:
            min_freq = 0

        # TODO: Correctly sort missing and other

        def format_row(freq, label, extra_class=''):
            width = int(freq / max_freq * 99) + 1
            if width > 30:
                label_in_bar = freq
                label_after_bar = ""
            else:
                label_in_bar = "&nbsp;"
                label_after_bar = freq

            return row_template.format(label=label,
                                       width=width,
                                       count=freq,
                                       percentage='{:2.1f}'.format(freq / n * 100),
                                       extra_class=extra_class,
                                       label_in_bar=label_in_bar,
                                       label_after_bar=label_after_bar)

        for label, freq in freqtable[0:max_number_of_items_in_table].iteritems():
            freq_rows_html += format_row(freq, label)

        if freq_other > min_freq:
            freq_rows_html += format_row(freq_other,
                                         "Other values (%s)" % (freqtable.count() - max_number_of_items_in_table),
                                         extra_class='other')

        if freq_missing > min_freq:
            freq_rows_html += format_row(freq_missing, "(Missing)", extra_class='missing')

        return table_template.format(rows=freq_rows_html, varid=hash(idx))

    # Overview
    overview_html = templates.overview_template.format({k: fmt(v, k) for k, v in stats_object['table'].iteritems()})

    # Variables
    rows_html = u""
    for idx, row in stats_object['variables'].iterrows():

        formatted_values = {'varname': idx, 'varid': hash(idx)}

        for col, value in row.iteritems():
            formatted_values[col] = unicode(fmt(value, col))

        if row['type'] == 'CAT':
            formatted_values['minifreqtable'] = freq_table(stats_object['freq'][idx], stats_object['table']['n'],
                                                           templates.mini_freq_table, templates.mini_freq_table_row, 3)
            formatted_values['freqtable'] = freq_table(stats_object['freq'][idx], stats_object['table']['n'],
                                                       templates.freq_table, templates.freq_table_row, 20)
        rows_html += templates.row_templates_dict[row['type']].format(formatted_values)

    # Sample

    sample_html = templates.sample_html.format(sample_table_html=sample_df.head().to_html(classes="sample"))

    return templates.base_html % {'overview_html': overview_html, 'rows_html': rows_html, 'sample_html': sample_html}


class ProfileReport(object):
    html = ''
    file = None

    def __init__(self, df):
        description_set = describe(df)
        self.html = to_html(df.head(),
                            description_set,
                            formatters=formatters.formatters)

    def to_file(self, outputfile=DEFAULT_OUTPUTFILE):
        if outputfile != NO_OUTPUTFILE:
            if outputfile == DEFAULT_OUTPUTFILE:
                outputfile = 'profile_' + str(hash(self)) + ".html"

            self.file = open(outputfile, 'w+b')
            self.file.write(templates.wrapper_html % self.html)
            self.file.close()

    def _repr_html_(self):
        return self.html

    def __str__(self):
        return "Output written to file " + str(self.file.name)


if __name__ == "__main__":
    import argparse
    import webbrowser

    parser = argparse.ArgumentParser(description='Profile the variables in a CSV file and generate a HTML report.')
    parser.add_argument("inputfile", help="CSV file to profile")
    parser.add_argument("-o", "--output", help="Output report file", default=DEFAULT_OUTPUTFILE)
    parser.add_argument("-s", "--silent", help="Only generate but do not open report", action="store_true")

    args = parser.parse_args()

    df = pd.read_csv(args.inputfile, sep=None, parse_dates=True)

    p = ProfileReport(df)
    p.to_file(outputfile=args.output)

    if not args.silent:
        webbrowser.open_new_tab(p.file.name)
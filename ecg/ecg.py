# -*- coding: utf-8 -*-
"""ECG (waveform) Dicom module

Read and plot images from DICOM ECG waveforms.
"""

from datetime import datetime
from matplotlib import pylab as plt
from scipy.signal import butter, lfilter
import numpy as np
import dicom
import struct
import cStringIO
import requests

from config import WADOSERVER, LAYOUT

__author__ = "Marco De Benedetto"
__email__ = "debe@galliera.it"


def butter_bandpass(lowcut, highcut, size, order=5):
    nyquist_freq = .5 * size
    low = lowcut / nyquist_freq
    high = highcut / nyquist_freq
    num, denom = butter(order, [low, high], btype='band')
    return num, denom


def butter_bandpass_filter(data, lowcut, highcut, size, order):
    num, denom = butter_bandpass(lowcut, highcut, size, order=order)
    return lfilter(num, denom, data)


class ECG(object):

    paper_w, paper_h = 297.0, 210.0

    # Dimensions in mm of plot area
    width = 250.0
    height = 170.0
    margin_left = margin_right = .5 * (paper_w - width)
    margin_bottom = 10

    # Normalized in [0, 1]
    left = margin_left/paper_w
    right = left+width/paper_w
    bottom = margin_bottom/paper_h
    top = bottom+height/paper_h

    def __init__(self, source, wadosrv=WADOSERVER):

        def err(msg):
            raise(Exception(msg))

        def wadoget(stu, ser, obj):

            payload = {'requestType': 'WADO', 'studyUID': stu,
                       'seriesUID': ser, 'objectUID': obj}
            headers = {'content-type': 'application/json'}

            resp = requests.get(wadosrv, params=payload, headers=headers)
            return cStringIO.StringIO(resp.content)

        if isinstance(source, dict):
            # dictionary of stu, ser, obj
            if set(source.keys()) == set(('stu', 'ser', 'obj')):
                inputdata = wadoget(**source)
            else:
                err("source must be a dictionary of stu, ser and obj")
        elif isinstance(source, basestring) or getattr(source, 'getvalue'):
            # it is a filename or a (StringIO or cStringIO buffer)
            inputdata = source
        else:
            # What is it?
            err("`source´ must be a path/to/file.ext string\n" +
                "or a dictionary of stu, ser and obj")

        self.dicom = dicom.read_file(inputdata)
        sequence_item = self.dicom.WaveformSequence[0]

        assert(sequence_item.WaveformSampleInterpretation == 'SS')
        assert(sequence_item.WaveformBitsAllocated == 16)

        self.channel_definitions = sequence_item.ChannelDefinitionSequence
        self.wavewform_data = sequence_item.WaveformData
        self.channels_no = sequence_item.NumberOfWaveformChannels
        self.samples = sequence_item.NumberOfWaveformSamples

        self.signals = self._signals()
        self.fig, self.axis = self.create_figure()

    def create_figure(self):
        """
        Prepare figure and axes
        """

        # Init figure and axes
        fig = plt.figure(tight_layout=False)
        axes = fig.add_subplot(1, 1, 1)
        # axes.set_frame_on(False)
        fig.subplots_adjust(left=self.left, right=self.right,
                            top=self.top, bottom=self.bottom)
        axes.set_ylim([0, self.height])
        # we want to plot N points, where N=number of samples
        axes.set_xlim([0, self.samples-1])
        return fig, axes

    def _signals(self):
        """
        sequence_item := dicom.dataset.FileDataset.WaveformData[n]
        Return a list of signals.
        """

        factor = np.zeros(self.channels_no) + 1
        baseln = np.zeros(self.channels_no)
        units = []
        for idx in range(self.channels_no):
            definition = self.channel_definitions[idx]

            assert(definition.WaveformBitsStored == 16)

            if definition.get('ChannelSensitivity'):
                factor[idx] = (
                    float(definition.ChannelSensitivity) *
                    float(definition.ChannelSensitivityCorrectionFactor))
            if definition.get('ChannelBaseline'):
                baseln[idx] = float(definition.get('ChannelBaseline'))

            units.append(
                definition.ChannelSensitivityUnitsSequence[0].CodeValue)

        signals = np.asarray(
            struct.unpack('<' + str(len(self.wavewform_data)/2) + 'h',
                          self.wavewform_data), dtype=np.float32).reshape(
                              self.samples, self.channels_no).transpose()

        for channel in range(self.channels_no):
            signals[channel] = (
                (signals[channel] + baseln[channel]) * factor[channel]
            )

        low = .05
        high = 40.0

        # conversion factor to obtain millivolts values
        millivolts = {'uV': 1000.0, 'mV': 1.0}

        for i, signal in enumerate(signals):
            signals[i] = butter_bandpass_filter(
                np.asarray(signal),
                low, high, 1000, order=1) / millivolts[units[i]]

        return signals

    def draw_grid(self):

        #self.axis.xaxis.set_minor_locator(plt.LinearLocator(self.width+1))
        self.axis.xaxis.set_major_locator(plt.LinearLocator(self.width/5+1))
        #self.axis.yaxis.set_minor_locator(plt.LinearLocator(self.height+1))
        self.axis.yaxis.set_major_locator(plt.LinearLocator(self.height/5+1))

        color = {'minor': '#ff5333', 'major': '#d43d1a'}
        linewidth = {'minor': .2, 'major': .6}
        alpha = 1

        for axe in 'x', 'y':
            for which in 'major', 'minor':
                self.axis.grid(which=which, axis=axe,
                               linewidth=linewidth[which],
                               linestyle='-', color=color[which], alpha=alpha)
                self.axis.tick_params(which=which, axis=axe,
                                      color=color[which],
                                      bottom='off', top='off',
                                      left='off', right='off')

        self.axis.set_xticklabels([])
        self.axis.set_yticklabels([])

    def legend(self):

        ecgdata = {}
        for was in self.dicom.WaveformAnnotationSequence:
            if was.get('ConceptNameCodeSequence'):
                cncs = was.ConceptNameCodeSequence[0]
                if cncs.CodeMeaning in ('QT Interval',
                                        'QTc Interval',
                                        'RR Interval',
                                        'QRS Duration',
                                        'QRS Axis',
                                        'T Axis',
                                        'P Axis',
                                        'PR Interval'):
                    ecgdata[cncs.CodeMeaning] = str(was.NumericValue)

        return 'Ventr. Freq.: ' + \
               str(60000 / int(ecgdata['RR Interval'])) + ' BPM\n' + \
               'PR Interval: ' + ecgdata['PR Interval'] + ' ms\n' + \
               'QRS Duration: ' + ecgdata['QRS Duration'] + ' ms\n' + \
               'QT/QTc: ' + \
               ecgdata['QT Interval'] + '/' + \
               ecgdata['QTc Interval'] + ' ms\n' + \
               'P-R-T Axis: ' + \
               ecgdata['P Axis'] + ' ' + \
               ecgdata['QRS Axis'] + ' ' + \
               ecgdata['T Axis'] + ' ms'

    def print_info(self):

        try:
            pat_surname, pat_firstname = self.dicom.PatientName.split('^')
        except ValueError:
            pat_surname = self.dicom.PatientName
            pat_firstname = ''

        pat_name = ' '.join((pat_surname, pat_firstname.title()))

        pat_id = self.dicom.PatientID
        pat_sex = self.dicom.PatientSex
        text_y = self.height+18

        ecg_date_str = (self.dicom.InstanceCreationDate +
                        self.dicom.InstanceCreationTime)
        ecg_date = datetime.strftime(datetime.strptime(ecg_date_str,
                                                       '%Y%m%d%H%M%S'),
                                     '%d %b %Y %H:%M')
        patient_str = "%s (%s) sex: %s" % (pat_name, pat_id, pat_sex)
        self.axis.text(0, text_y, patient_str, fontsize=12)
        self.axis.text(0, text_y-5, "ECG date: " + ecg_date, fontsize=10)

    def save(self, outputfile=None, outformat=None):

        def _save(output):
            plt.savefig(output, dpi=300, format=outformat,
                        papertype='a4', orientation='landscape')

        if outputfile:
            _save(outputfile)
        else:
            output = cStringIO.StringIO()
            _save(output)
            return output.getvalue()

    def plot(self, layoutid):

        layout = LAYOUT[layoutid]
        rows = len(layout)

        for numrow, row in enumerate(layout):
            columns = len(row)
            h_delta = self.samples / columns
            signal = np.ndarray(0)
            row_height = self.height / rows
            v_delta = round(self.height * (1 - 1.0/(rows*2)) -
                            numrow*(self.height/rows))

            v_delta = (v_delta + 2.5) - (v_delta + 2.5) % 5
            chunk_size = int(self.samples/len(row))

            for numcol, signum in enumerate(row):
                left = numcol*chunk_size
                right = (1+numcol)*chunk_size
                h = h_delta * numcol
                plt.plot([h, h], [v_delta-row_height/2.6,
                                  v_delta+row_height/2.6],
                         'k-', lw=1, color='blue', zorder=50)
                signal = np.concatenate((
                    signal,
                    10.0*self.signals[signum][left:right])
                )
                cseq = self.channel_definitions[signum].ChannelSourceSequence
                meaning = cseq[0].CodeMeaning.replace(
                    'Lead', '').replace('(Einthoven)', '')
                self.axis.text(h+40, v_delta+row_height/3,
                               meaning, color='b', zorder=50)

            self.axis.text(4000, self.height+2, self.legend(),
                           fontsize=10, color='k', zorder=50)

            self.axis.plot(signal+v_delta, linewidth=.6, color='black',
                           antialiased=True, zorder=10)

        # A4 size in inches
        self.fig.set_size_inches(11.69, 8.27)

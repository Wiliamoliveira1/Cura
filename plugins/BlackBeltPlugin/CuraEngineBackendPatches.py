from UM.Application import Application
from UM.Logger import Logger
from UM.Backend.Backend import BackendState
from UM.Qt.Duration import DurationFormat

from . import ProcessSlicedLayersJob
from . import StartSliceJob

from time import time

class CuraEngineBackendPatches():
    def __init__(self, backend):
        self._backend = backend

        self._backend._change_timer.timeout.disconnect(self._backend.slice)
        self._backend.slice = self.slice
        self._backend._change_timer.timeout.connect(self.slice)

        self._backend._startProcessSlicedLayersJob = self._startProcessSlicedLayersJob

    ##  Perform a slice of the scene.
    def slice(self):
        Logger.log("d", "starting to slice!")
        self._backend._slice_start_time = time()
        if not self._backend._build_plates_to_be_sliced:
            self._backend.processingProgress.emit(1.0)
            Logger.log("w", "Slice unnecessary, nothing has changed that needs reslicing.")
            return

        if self._backend._process_layers_job:
            Logger.log("d", "  ## Process layers job still busy, trying later")
            return

        if not hasattr(self._backend._scene, "gcode_dict"):
            self._backend._scene.gcode_dict = {}

        # see if we really have to slice
        active_build_plate = Application.getInstance().getBuildPlateModel().activeBuildPlate
        build_plate_to_be_sliced = self._backend._build_plates_to_be_sliced.pop(0)
        Logger.log("d", "Going to slice build plate [%s]!" % build_plate_to_be_sliced)
        num_objects = self._backend._numObjects()
        if build_plate_to_be_sliced not in num_objects or num_objects[build_plate_to_be_sliced] == 0:
            self._backend._scene.gcode_dict[build_plate_to_be_sliced] = []
            Logger.log("d", "Build plate %s has no objects to be sliced, skipping", build_plate_to_be_sliced)
            if self._backend._build_plates_to_be_sliced:
                self._backend.slice()
            return

        self._backend._stored_layer_data = []
        self._backend._stored_optimized_layer_data[build_plate_to_be_sliced] = []

        if Application.getInstance().getPrintInformation() and build_plate_to_be_sliced == active_build_plate:
            Application.getInstance().getPrintInformation().setToZeroPrintInformation(build_plate_to_be_sliced)

        if self._backend._process is None:
            self._backend._createSocket()
        self._backend.stopSlicing()
        self._backend._engine_is_fresh = False  # Yes we're going to use the engine

        self._backend.processingProgress.emit(0.0)
        self._backend.backendStateChange.emit(BackendState.NotStarted)

        self._backend._scene.gcode_dict[build_plate_to_be_sliced] = []  #[] indexed by build plate number
        self._backend._slicing = True
        self._backend.slicingStarted.emit()

        self._backend.determineAutoSlicing()  # Switch timer on or off if appropriate

        slice_message = self._backend._socket.createMessage("cura.proto.Slice")
        self._backend._start_slice_job = StartSliceJob.StartSliceJob(slice_message)
        self._backend._start_slice_job_build_plate = build_plate_to_be_sliced
        self._backend._start_slice_job.setBuildPlate(self._backend._start_slice_job_build_plate)
        self._backend._start_slice_job.start()
        self._backend._start_slice_job.finished.connect(self._backend._onStartSliceCompleted)

    def _startProcessSlicedLayersJob(self, build_plate_number):
        self._backend._process_layers_job = ProcessSlicedLayersJob.ProcessSlicedLayersJob(self._backend._stored_optimized_layer_data[build_plate_number])
        self._backend._process_layers_job.setBuildPlate(build_plate_number)
        self._backend._process_layers_job.finished.connect(self._backend._onProcessLayersFinished)
        self._backend._process_layers_job.start()

    ##  Called when the user changes the active view mode.
    def _onActiveViewChanged(self):
        view = Application.getInstance().getController().getActiveView()
        if view:
            if view.getPluginId() == "SimulationView":  # If switching to layer view, we should process the layers if that hasn't been done yet.
                self._backend._layer_view_active = True
                # There is data and we're not slicing at the moment
                # if we are slicing, there is no need to re-calculate the data as it will be invalid in a moment.
            if self._backend._layer_view_active and (self._backend._process_layers_job is None or not self._backend._process_layers_job.isRunning()):
                self._backend._process_layers_job = ProcessSlicedLayersJob.ProcessSlicedLayersJob(self._backend._stored_optimized_layer_data)
                self._backend._process_layers_job.finished.connect(self._backend._onProcessLayersFinished)
                self._backend._process_layers_job.start()
                self._backend._stored_optimized_layer_data = []
            else:
                self._backend._layer_view_active = False
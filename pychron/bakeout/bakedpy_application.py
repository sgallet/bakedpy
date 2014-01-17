#===============================================================================
# Copyright 2011 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#===============================================================================

#============= enthought library imports =======================
# from envisage.ui.workbench.api import WorkbenchApplication
# from pyface.api import AboutDialog, SplashScreen
# from pyface.image_resource import ImageResource
#============= standard library imports ========================

#============= local library imports  ==========================
from pyface.tasks.task_window_layout import TaskWindowLayout
from pychron.applications.pychron_application import PychronApplication

class Bakedpy(PychronApplication):
    '''
    '''
    id = 'tasks.bakedpy'
    name = 'Bakedpy'

    default_layout = [TaskWindowLayout('bakeout.main',
                                       size=(800, 800)) ]

#============= views ===================================
#============= EOF ====================================

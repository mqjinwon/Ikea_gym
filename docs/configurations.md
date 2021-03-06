# Configuration

We offer many configuration options on both the MuJoCo simulation and Unity rendering. The simulation configurations will be exposed through command line arguments.
## Observations
The following list describes the possible keys in the observation dictionary. Some may or may not be present depending on the observation flags set.

* The robot ob is a dictionary of positions, angles, and velocities of the agent. See the `get_obs` function
of each agent in `furniture_*.py` for the specifics.
* The object ob is a dictionary that holds furniture parts and their corresponding pose (position and quaternion).
* The subtask ob is a numpy array of two integers which represent ids (1 ~ # parts) of two parts can be attached. If the furniture is complete, it is set to (0, 0).
* The visual ob is an (N x H x W x C) array of RGB camera images where N is the number of cameras.
* The segmentation ob is an (N x H x W) array of segmentation maps where N is the number of cameras.
* The depth ob is an (N x H x W) array of depth images where N is the number of cameras.

### Multiple Cameras and Wrist Camera
To add more cameras, you can add additional mujoco camera element to `env/models/assets/arenas/floor_arena.xml`. Use `--camera_ids` to specify which cameras you want to enable for rendering. For example, `--camera_ids 0,3` will render the 1st and 4th camera that exists in the XML.

A wrist camera example can be found in the Sawyer xml `env/models/assets/robots/sawyer/robot.xml`. You can add similar cameras to the other robot's XML to enable wrist camera recording. Run `demo_vision.py` with the Sawyer robot to see an example.

|<img src="img/observations/multicam.png" width="400">|
| :----------:|
|An example rendering of multiple cameras and their modalities, including a wrist camera|

## Robots
To switch between agent configuration, simply select the corresponding python script.
```
# sawyer
$ python -m env.furniture_sawyer ...

# cursor
$ python -m env.furniture_cursor ...
```
OR run demo_\<yourtask\>.py script and select agent from the choices presented in the terminal
  ```
# manipulating agent manually
$ python -m demo_manual ...

# RL training
$ python -m demo_rl ...
```

## Furniture Models
Preferably use the `--furniture_name` argument to choose a furniture model. `--furniture_id` may also be used but is not recommended, because the ids are determined dynamically by sorting the xml files in the directory. Therefore, if more furniture is added, the IDs may change. Use the `furniture_name` argument to get the exact furniture you want. See [`furniture/env/models/__init__.py`](../env/models/__init__.py) for more details.

Some furniture pieces (e.g. flat plane) are difficult to grasp using grippers we currently support.
This can be addressed by initializing the difficult parts in a predefined, easy to grasp way. See
[Designing a new task](creating_task.md) for how to customize initialization.

## Assembly Configuration
Two parts will be assembled when an agent activates `connect` action and two parts are well-aligned.
The thresholds for determining successful connection are defined by distance between two connectors `pos_dist`, cosine similarity between up vectors of connectors `rot_siml_up`, cosine similarity between forward vectors of connectors `rot_siml_forward`, and relative pose of two connectors `project_dist`. These values are configurable by changing those values in [`furniture/env/furniture.py`](../env/furniture.py). Please refer to `_is_aligned(connector1, connector2)` method in [`furniture/env/furniture.py`](../env/furniture.py) for details.

## Background Scenes

<img src="img/env/allenv.gif" width="200">

Use `--background` argument to choose a background scene.

- Garage: flat ground environment
- Interior: flat ground, interior decoration
- Lab: flat ground, bright lighting
- Industrial: cluttered objects, directional lighting
- NightTime: flat ground, dim lighting
- Ambient: flat ground, colored lighting

Note that objects in the Unity scene are not physically simulated. For example, the table is just an overlay of the invisible mujoco ground plane.

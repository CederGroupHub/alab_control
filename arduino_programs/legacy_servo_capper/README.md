# Legacy servo capper (unused by ALab One DASH)

Historical servo open/close gripper firmware. Live DASH uses
``arduino_programs/capper`` (grippers + spin motor) and ``alab_control.capper``.

## APIs
- `/open`
  
  Open the capper and release the vial. 
  - When opened successfully, the capper will return a `200` status code with 
    ```json
    {
      "status": "success"
    }
    ```
  - When the capper is open, the capper will return a `400` status code with
      ```json
      {
        "status": "error",
        "reason": "The capper is already open."
      }
      ```

- `/close`
  
    Close the capper and hold the vial.
    - When closed successfully, the capper will return a `200` status code with 
        ```json
        {
          "status": "success"
        }
        ```
      - When the capper is closed, the capper will return a `400` status code with
          ```json
          {
            "status": "error",
            "reason": "The capper is already closed."
          }
          ```
- `/state`

    Get the current state of the capper.
    - When the capper is closed, the capper will return a `200` status code with
        ```json
        {
          "status": "success",
          "state": "closed"
        }
        ```
    - When the capper is open, the capper will return a `200` status code with
        ```json
        {
          "status": "success",
          "state": "open"
        }
        ```
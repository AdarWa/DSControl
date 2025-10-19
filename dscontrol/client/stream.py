import cv2

# Replace with server IP
url = "tcp://192.168.1.10:9999"

cap = cv2.VideoCapture(url)

if not cap.isOpened():
    print("Failed to connect to stream.")
    exit()

while True:
    ret, frame = cap.read()
    if not ret:
        break
    cv2.imshow("Remote Window", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()

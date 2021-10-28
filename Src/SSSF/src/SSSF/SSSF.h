#ifndef SSSF_H_
#define SSSF_H_

#include <Arduino.h>
#include <SensorNode/SensorNode.h>
#include <HTTP/HTTPClient.h>
#include <EthernetUdp.h>
#include <ArduinoJson.h>
#include <IPAddress.h>
#include <NTPClient.h>
#include <FlexCAN_T4.h>

class SSSF: private SensorNode, private HTTPClient
{
private:
    const char *serverAddress = "ETS00853";
    uint32_t id;
    uint32_t frameNumber;
    EthernetUDP ntpSock;
    NTPClient timeClient;

    FlexCAN_T4<CAN0, RX_SIZE_256, TX_SIZE_16> can0;
    FlexCAN_T4<CAN1, RX_SIZE_256, TX_SIZE_16> can1;
    uint32_t can0BaudRate;
    uint32_t can1BaudRate;

public:
    struct COMMBlock
    {
        uint32_t id;
        uint32_t frameNumber;
        uint8_t type;
        union
        {
            struct WSensorBlock sensorFrame;
            struct WCANBlock canFrame;
        };
    };

    SSSF(DynamicJsonDocument _attachedDevice, uint32_t _can0Baudrate);
    SSSF(DynamicJsonDocument _attachedDevice, uint32_t _can0Baudrate, uint32_t can1Baudrate);

    virtual bool setup();
    virtual void forwardingLoop();

    virtual void write(struct CAN_message_t *canFrame);
    virtual void write(struct CANFD_message_t *canFrame);

private:
    void setupClock();
    void setupCANChannels();

    void pollClock();
    void pollServer();
    void pollCANNetwork();

    void startSession(struct Request *request);
};

#endif /* SSSF_H_ */
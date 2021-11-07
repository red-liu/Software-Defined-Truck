#ifndef network_stats_h_
#define network_stats_h_

#include <Arduino.h>
#include <CANNode/CANNode.h>
#include <limits>
#include <FlexCAN_T4.h>

class NetworkStats
{
private:
    uint16_t id;
    uint16_t *members;

    float delta = 0;
    float delta2 = 0;

public:
    struct HealthBasics
    {
        uint32_t lastMessageTime = millis();
        uint32_t lastSequenceNumber = 0;
        float M2 = 0.0;
    };

    struct HealthCore
    {
        uint32_t count = 0;
        float min = std::numeric_limits<float>::max();
        float max = -std::numeric_limits<float>::max();
        float mean = 0.0;
        float variance = 0.0;
    };

    struct NodeReport
    {
        float packetLoss;
        struct HealthCore latency;
        struct HealthCore jitter;
        struct HealthCore throughput;
    };

    size_t size = 0;
    struct HealthBasics *Basics;
    struct NodeReport *HealthReport;

    NetworkStats(uint16_t _id, uint16_t *_members, size_t _size);
    ~NetworkStats();
    void update(uint16_t _id, int packetSize, uint32_t timestamp, uint32_t sequenceNumber);
    void reset();
    // TODO: Reset every health report keep last seen sequence number

private:
    void calculate(struct HealthCore &edge, uint32_t &count, float n);
};

#endif /* network_stats_h_ */